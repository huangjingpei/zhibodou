//
//  PdkVideoEncoder.m
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import "PdkVideoEncoder.h"

@interface PdkVideoEncoder () {
    VTCompressionSessionRef _compressionSession;
    dispatch_queue_t _encodeQueue;
    int _width;
    int _height;
    int _fps;
    int _bitrateKbps;
    int64_t _firstPtsMs;
    BOOL _hasSentHeader;
}
@end

static void CompressionOutputCallback(
    void *outputCallbackRefCon,
    void *sourceFrameRefCon,
    OSStatus status,
    VTEncodeInfoFlags infoFlags,
    CMSampleBufferRef sampleBuffer
) {
    if (status != noErr || !sampleBuffer) {
        return;
    }

    PdkVideoEncoder *encoder = (__bridge PdkVideoEncoder *)outputCallbackRefCon;
    [encoder handleEncodedSampleBuffer:sampleBuffer];
}

@implementation PdkVideoEncoder

- (instancetype)init {
    self = [super init];
    if (self) {
        _encodeQueue = dispatch_queue_create("com.zhibodou.mobile.videoEncodeQueue", DISPATCH_QUEUE_SERIAL);
        _firstPtsMs = -1;
        _hasSentHeader = NO;
    }
    return self;
}

- (BOOL)prepareWithWidth:(int)width
                  height:(int)height
                     fps:(int)fps
             bitrateKbps:(int)bitrateKbps {
    [self stop];

    _width = width;
    _height = height;
    _fps = fps > 0 ? fps : 30;
    _bitrateKbps = bitrateKbps > 0 ? bitrateKbps : 1800;
    _firstPtsMs = -1;
    _hasSentHeader = NO;

    OSStatus status = VTCompressionSessionCreate(
        kCFAllocatorDefault,
        _width,
        _height,
        kCMVideoCodecType_H264,
        NULL,
        NULL,
        NULL,
        CompressionOutputCallback,
        (__bridge void *)self,
        &_compressionSession
    );

    if (status != noErr || !_compressionSession) {
        NSLog(@"[PdkVideoEncoder] VTCompressionSessionCreate failed with status %d", (int)status);
        return NO;
    }

    // 1. 设置实时推流低延迟模式 (RealTime)
    VTSessionSetProperty(_compressionSession, kVTCompressionPropertyKey_RealTime, kCFBooleanTrue);
    VTSessionSetProperty(_compressionSession, kVTCompressionPropertyKey_ProfileLevel, kVTProfileLevel_H264_High_AutoLevel);
    VTSessionSetProperty(_compressionSession, kVTCompressionPropertyKey_AllowFrameReordering, kCFBooleanFalse);

    // 2. 设置关键帧间隔 (GOP = 2秒)
    int gop = _fps * 2;
    VTSessionSetProperty(_compressionSession, kVTCompressionPropertyKey_MaxKeyFrameInterval, (__bridge CFTypeRef)@(gop));
    VTSessionSetProperty(_compressionSession, kVTCompressionPropertyKey_MaxKeyFrameIntervalDuration, (__bridge CFTypeRef)@(2));

    // 3. 设置目标码率 (bits per second) 与动态缓冲上限
    int bitrateBps = _bitrateKbps * 1000;
    VTSessionSetProperty(_compressionSession, kVTCompressionPropertyKey_AverageBitRate, (__bridge CFTypeRef)@(bitrateBps));
    NSArray *limits = @[@(bitrateBps * 1.5 / 8), @(1)];
    VTSessionSetProperty(_compressionSession, kVTCompressionPropertyKey_DataRateLimits, (__bridge CFArrayRef)limits);

    // 4. 准备开始编码
    status = VTCompressionSessionPrepareToEncodeFrames(_compressionSession);
    if (status != noErr) {
        NSLog(@"[PdkVideoEncoder] PrepareToEncodeFrames failed: %d", (int)status);
        [self stop];
        return NO;
    }

    _isEncoding = YES;
    NSLog(@"[PdkVideoEncoder] 视频硬编码器准备就绪: %dx%d @ %dfps, 码率: %d kbps", _width, _height, _fps, _bitrateKbps);
    return YES;
}

- (void)encodeSampleBuffer:(CMSampleBufferRef)sampleBuffer {
    if (!_isEncoding || !_compressionSession || !sampleBuffer) {
        return;
    }

    CVImageBufferRef imageBuffer = CMSampleBufferGetImageBuffer(sampleBuffer);
    if (!imageBuffer) return;

    CMTime presentationTimeStamp = CMSampleBufferGetPresentationTimeStamp(sampleBuffer);
    CMTime duration = CMSampleBufferGetDuration(sampleBuffer);

    VTEncodeInfoFlags flags;
    VTCompressionSessionEncodeFrame(
        _compressionSession,
        imageBuffer,
        presentationTimeStamp,
        duration,
        NULL,
        NULL,
        &flags
    );
}

- (void)handleEncodedSampleBuffer:(CMSampleBufferRef)sampleBuffer {
    // 检查是否包含关键帧 (IDR)
    CFArrayRef attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, false);
    BOOL isKeyframe = NO;
    if (attachments && CFArrayGetCount(attachments) > 0) {
        CFDictionaryRef dict = (CFDictionaryRef)CFArrayGetValueAtIndex(attachments, 0);
        isKeyframe = !CFDictionaryContainsKey(dict, kCMSampleAttachmentKey_NotSync);
    }

    CMFormatDescriptionRef format = CMSampleBufferGetFormatDescription(sampleBuffer);

    // 1. 如果是关键帧且尚未发送或需要刷新 SPS/PPS
    if (isKeyframe && format) {
        size_t spsSize, spsCount;
        const uint8_t *sps;
        OSStatus spsStatus = CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
            format, 0, &sps, &spsSize, &spsCount, NULL);

        size_t ppsSize, ppsCount;
        const uint8_t *pps;
        OSStatus ppsStatus = CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
            format, 1, &pps, &ppsSize, &ppsCount, NULL);

        if (spsStatus == noErr && ppsStatus == noErr) {
            NSData *spsData = [NSData dataWithBytes:sps length:spsSize];
            NSData *ppsData = [NSData dataWithBytes:pps length:ppsSize];
            if (!_hasSentHeader) {
                _hasSentHeader = YES;
                [self.delegate videoEncoderDidOutputSps:spsData pps:ppsData];
            }
        }
    }

    // 2. 提取 NALU 数据
    CMBlockBufferRef blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer);
    if (!blockBuffer) return;

    size_t totalLength = 0;
    char *dataPointer = NULL;
    OSStatus status = CMBlockBufferGetDataPointer(blockBuffer, 0, NULL, &totalLength, &dataPointer);
    if (status != noErr || !dataPointer || totalLength <= 0) return;

    NSData *naluData = [NSData dataWithBytes:dataPointer length:totalLength];

    // 计算相对时间戳 (毫秒)
    CMTime ptsTime = CMSampleBufferGetPresentationTimeStamp(sampleBuffer);
    CMTime dtsTime = CMSampleBufferGetDecodeTimeStamp(sampleBuffer);
    if (!CMTIME_IS_VALID(dtsTime)) {
        dtsTime = ptsTime;
    }

    int64_t currentPtsMs = (int64_t)(CMTimeGetSeconds(ptsTime) * 1000);
    int64_t currentDtsMs = (int64_t)(CMTimeGetSeconds(dtsTime) * 1000);

    if (_firstPtsMs < 0) {
        _firstPtsMs = currentPtsMs;
    }

    uint32_t relPts = (uint32_t)MAX(0, currentPtsMs - _firstPtsMs);
    uint32_t relDts = (uint32_t)MAX(0, currentDtsMs - _firstPtsMs);

    [self.delegate videoEncoderDidOutputNaluData:naluData pts:relPts dts:relDts isKeyframe:isKeyframe];
}

- (void)setBitrate:(int)bitrateKbps {
    if (!_compressionSession || bitrateKbps <= 0) return;
    _bitrateKbps = bitrateKbps;
    int bitrateBps = bitrateKbps * 1000;

    NSLog(@"[PdkVideoEncoder] VideoToolbox 动态调整码率: %d kbps (%d bps)", bitrateKbps, bitrateBps);
    VTSessionSetProperty(_compressionSession, kVTCompressionPropertyKey_AverageBitRate, (__bridge CFTypeRef)@(bitrateBps));
    NSArray *limits = @[@(bitrateBps * 1.5 / 8), @(1)];
    VTSessionSetProperty(_compressionSession, kVTCompressionPropertyKey_DataRateLimits, (__bridge CFArrayRef)limits);
}

- (void)stop {
    _isEncoding = NO;
    if (_compressionSession) {
        VTCompressionSessionInvalidate(_compressionSession);
        CFRelease(_compressionSession);
        _compressionSession = NULL;
    }
    _firstPtsMs = -1;
    _hasSentHeader = NO;
}

- (void)dealloc {
    [self stop];
}

@end
