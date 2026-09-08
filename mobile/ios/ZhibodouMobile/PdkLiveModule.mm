//
//  PdkLiveModule.mm
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import "PdkLiveModule.h"
#import "PdkLiveManager.h"
#import "PdkCaptureEngine.h"
#import "PdkVideoEncoder.h"
#import "PdkAudioEncoder.h"
#import "PdkRtmpClient.h"

@interface PdkLiveModule () <PdkCaptureEngineDelegate, PdkVideoEncoderDelegate, PdkAudioEncoderDelegate, PdkRtmpClientDelegate> {
    PdkCaptureEngine *_captureEngine;
    PdkVideoEncoder *_videoEncoder;
    PdkAudioEncoder *_audioEncoder;
    PdkRtmpClient *_rtmpClient;

    BOOL _hasListeners;
    BOOL _isPublishing;
    int _currentBitrateKbps;
    uint32_t _lastBitrateBps;
    int _streamDurationSeconds;
    int _targetFps;

    dispatch_source_t _statsTimer;
}
@end

@implementation PdkLiveModule

RCT_EXPORT_MODULE(PdkLiveModule);

+ (BOOL)requiresMainQueueSetup {
    return YES;
}

- (instancetype)init {
    self = [super init];
    if (self) {
        _captureEngine = [[PdkCaptureEngine alloc] init];
        _captureEngine.delegate = self;

        _videoEncoder = [[PdkVideoEncoder alloc] init];
        _videoEncoder.delegate = self;

        _audioEncoder = [[PdkAudioEncoder alloc] init];
        _audioEncoder.delegate = self;

        _rtmpClient = [[PdkRtmpClient alloc] init];
        _rtmpClient.delegate = self;

        _isPublishing = NO;
        _currentBitrateKbps = 1800;
        _lastBitrateBps = 0;
        _streamDurationSeconds = 0;
        _targetFps = 30;

        [PdkLiveManager sharedInstance].currentLiveModule = self;
    }
    return self;
}

- (NSArray<NSString *> *)supportedEvents {
    return @[@"onStreamStats", @"onStreamStateChanged"];
}

- (void)startObserving {
    _hasListeners = YES;
}

- (void)stopObserving {
    _hasListeners = NO;
}

#pragma mark - React Native 导出方法

RCT_EXPORT_METHOD(startPreview:(BOOL)isFront
                  width:(NSInteger)width
                  height:(NSInteger)height
                  fps:(NSInteger)fps
                  resolver:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject) {
    dispatch_async(dispatch_get_main_queue(), ^{
        int actualFps = fps > 0 ? (int)fps : 30;
        self->_targetFps = actualFps;

        BOOL ok = [self->_captureEngine startPreviewWithFront:isFront fps:actualFps];
        [[PdkLiveManager sharedInstance] attachCaptureSession:self->_captureEngine.captureSession];

        resolve(@(ok));
    });
}

RCT_EXPORT_METHOD(stopPreview:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject) {
    dispatch_async(dispatch_get_main_queue(), ^{
        [self->_captureEngine stopPreview];
        [[PdkLiveManager sharedInstance] attachCaptureSession:nil];
        resolve(@(YES));
    });
}

RCT_EXPORT_METHOD(startPublish:(NSString *)streamUrl
                  width:(NSInteger)width
                  height:(NSInteger)height
                  fps:(NSInteger)fps
                  bitrateKbps:(NSInteger)bitrateKbps
                  audioBitrateKbps:(NSInteger)audioBitrateKbps
                  sampleRate:(NSInteger)sampleRate
                  resolver:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject) {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (self->_isPublishing) {
            resolve(@(YES));
            return;
        }

        int targetW = width > 0 ? (int)width : 1080;
        int targetH = height > 0 ? (int)height : 1920;
        int targetFps = fps > 0 ? (int)fps : 30;
        self->_targetFps = targetFps;
        self->_currentBitrateKbps = bitrateKbps > 0 ? (int)bitrateKbps : 1800;
        int targetAudioBitrate = audioBitrateKbps > 0 ? (int)audioBitrateKbps : 128;
        int targetSampleRate = sampleRate > 0 ? (int)sampleRate : 48000;

        NSLog(@"[PdkLiveModule] startPublish: %dx%d @ %dfps, videoBitrate=%d kbps, audioBitrate=%d kbps",
              targetW, targetH, targetFps, self->_currentBitrateKbps, targetAudioBitrate);

        // 1. 启动取景采集
        if (!self->_captureEngine.isRunning) {
            [self->_captureEngine startPreviewWithFront:self->_captureEngine.isFrontCamera fps:targetFps];
            [[PdkLiveManager sharedInstance] attachCaptureSession:self->_captureEngine.captureSession];
        }

        // 2. 准备硬件编码器
        BOOL vOk = [self->_videoEncoder prepareWithWidth:targetW height:targetH fps:targetFps bitrateKbps:self->_currentBitrateKbps];
        if (!vOk) {
            reject(@"CODEC_VIDEO_ERR", @"无法初始化 iOS VideoToolbox H.264 视频硬编码器", nil);
            return;
        }

        BOOL aOk = [self->_audioEncoder prepareWithSampleRate:targetSampleRate channels:1 bitrateKbps:targetAudioBitrate];
        if (!aOk) {
            reject(@"CODEC_AUDIO_ERR", @"无法初始化 iOS AudioToolbox AAC 音频硬编码器", nil);
            return;
        }

        // 3. 建立 RTMP 连接
        self->_isPublishing = YES;
        self->_streamDurationSeconds = 0;
        self->_lastBitrateBps = 0;

        [self notifyStateChanged:@"CONNECTING" error:nil];

        BOOL cOk = [self->_rtmpClient connectWithUrl:streamUrl
                                              width:targetW
                                             height:targetH
                                                fps:targetFps
                                        bitrateKbps:self->_currentBitrateKbps
                                   audioBitrateKbps:targetAudioBitrate
                                         sampleRate:targetSampleRate];
        if (!cOk) {
            self->_isPublishing = NO;
            reject(@"RTMP_CONNECT_ERR", @"RTMP 连接请求失败，请检查 URL", nil);
            return;
        }

        [self startStatsTimer];
        resolve(@(YES));
    });
}

RCT_EXPORT_METHOD(stopPublish:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject) {
    dispatch_async(dispatch_get_main_queue(), ^{
        self->_isPublishing = NO;
        [self stopStatsTimer];

        [self->_rtmpClient disconnect];
        [self->_videoEncoder stop];
        [self->_audioEncoder stop];

        [self notifyStateChanged:@"DISCONNECTED" error:nil];

        // 保持摄像头预览常驻，确保主播取景不黑屏
        if (!self->_captureEngine.isRunning) {
            [self->_captureEngine startPreviewWithFront:self->_captureEngine.isFrontCamera fps:self->_targetFps];
            [[PdkLiveManager sharedInstance] attachCaptureSession:self->_captureEngine.captureSession];
        }

        resolve(@(YES));
    });
}

RCT_EXPORT_METHOD(switchCamera:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject) {
    dispatch_async(dispatch_get_main_queue(), ^{
        BOOL ok = [self->_captureEngine switchCamera];
        resolve(@(self->_captureEngine.isFrontCamera));
    });
}

RCT_EXPORT_METHOD(toggleTorch:(BOOL)enable
                  resolver:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject) {
    dispatch_async(dispatch_get_main_queue(), ^{
        BOOL ok = [self->_captureEngine toggleTorch:enable];
        resolve(@(self->_captureEngine.isTorchOn));
    });
}

RCT_EXPORT_METHOD(setMute:(BOOL)mute
                  resolver:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject) {
    dispatch_async(dispatch_get_main_queue(), ^{
        [self->_captureEngine setMuted:mute];
        resolve(@(mute));
    });
}

RCT_EXPORT_METHOD(setBitrate:(NSInteger)bitrateKbps
                  resolver:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject) {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (bitrateKbps > 0) {
            self->_currentBitrateKbps = (int)bitrateKbps;
            NSLog(@"[PdkLiveModule] 动态调整推流视频码率: %d kbps", self->_currentBitrateKbps);
            [self->_videoEncoder setBitrate:(int)bitrateKbps];
        }
        resolve(@(YES));
    });
}

RCT_EXPORT_METHOD(getStatus:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject) {
    dispatch_async(dispatch_get_main_queue(), ^{
        NSDictionary *status = @{
            @"isStreaming": @(self->_isPublishing && self->_rtmpClient.isConnected),
            @"isOnPreview": @(self->_captureEngine.isRunning),
            @"isFrontFacing": @(self->_captureEngine.isFrontCamera),
            @"isLanternEnabled": @(self->_captureEngine.isTorchOn),
            @"isAudioMuted": @(self->_captureEngine.isMuted)
        };
        resolve(status);
    });
}

#pragma mark - PdkCaptureEngineDelegate

- (void)captureEngineDidOutputVideoSampleBuffer:(CMSampleBufferRef)sampleBuffer {
    if (_isPublishing && _videoEncoder.isEncoding) {
        [_videoEncoder encodeSampleBuffer:sampleBuffer];
    }
}

- (void)captureEngineDidOutputAudioSampleBuffer:(CMSampleBufferRef)sampleBuffer {
    if (_isPublishing && _audioEncoder.isEncoding) {
        [_audioEncoder encodeSampleBuffer:sampleBuffer];
    }
}

#pragma mark - PdkVideoEncoderDelegate

- (void)videoEncoderDidOutputSps:(NSData *)sps pps:(NSData *)pps {
    [_rtmpClient sendVideoHeaderWithSps:sps pps:pps];
}

- (void)videoEncoderDidOutputNaluData:(NSData *)naluData pts:(uint32_t)pts dts:(uint32_t)dts isKeyframe:(BOOL)isKeyframe {
    [_rtmpClient sendVideoData:naluData pts:pts dts:dts isKeyframe:isKeyframe];
}

#pragma mark - PdkAudioEncoderDelegate

- (void)audioEncoderDidOutputAsc:(NSData *)asc {
    [_rtmpClient sendAudioHeaderWithAsc:asc];
}

- (void)audioEncoderDidOutputAacData:(NSData *)aacData pts:(uint32_t)pts {
    [_rtmpClient sendAudioData:aacData pts:pts];
}

#pragma mark - PdkRtmpClientDelegate

- (void)rtmpClientDidConnect {
    [self notifyStateChanged:@"CONNECTED" error:nil];
}

- (void)rtmpClientDidFailWithError:(NSString *)error {
    _isPublishing = NO;
    [self stopStatsTimer];
    [self notifyStateChanged:@"FAILED" error:error];
}

- (void)rtmpClientDidDisconnect {
    _isPublishing = NO;
    [self stopStatsTimer];
    [self notifyStateChanged:@"DISCONNECTED" error:nil];
}

- (void)rtmpClientDidUpdateBitrate:(uint32_t)bitrateBps {
    _lastBitrateBps = bitrateBps;
}

#pragma mark - 统计上报与事件推送

- (void)startStatsTimer {
    [self stopStatsTimer];

    _statsTimer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, dispatch_get_main_queue());
    dispatch_source_set_timer(_statsTimer, dispatch_time(DISPATCH_TIME_NOW, 1 * NSEC_PER_SEC), 1 * NSEC_PER_SEC, 100 * NSEC_PER_MSEC);

    __weak typeof(self) weakSelf = self;
    dispatch_source_set_event_handler(_statsTimer, ^{
        __strong typeof(weakSelf) strongSelf = weakSelf;
        if (!strongSelf || !strongSelf->_isPublishing) return;

        strongSelf->_streamDurationSeconds++;
        int kbps = strongSelf->_lastBitrateBps > 0 ? (int)(strongSelf->_lastBitrateBps / 1000) : strongSelf->_currentBitrateKbps;

        NSString *netQuality = @"GOOD";
        if (kbps >= 2000) {
            netQuality = @"EXCELLENT";
        } else if (kbps < 800) {
            netQuality = @"POOR";
        }

        NSDictionary *stats = @{
            @"fps": @(strongSelf->_targetFps),
            @"bitrateKbps": @(kbps),
            @"droppedFrames": @(0),
            @"durationSeconds": @(strongSelf->_streamDurationSeconds),
            @"netQuality": netQuality
        };

        if (strongSelf->_hasListeners) {
            [strongSelf sendEventWithName:@"onStreamStats" body:stats];
        }
    });

    dispatch_resume(_statsTimer);
}

- (void)stopStatsTimer {
    if (_statsTimer) {
        dispatch_source_cancel(_statsTimer);
        _statsTimer = nil;
    }
}

- (void)notifyStateChanged:(NSString *)state error:(nullable NSString *)error {
    if (!_hasListeners) return;

    NSMutableDictionary *body = [NSMutableDictionary dictionaryWithObject:state forKey:@"state"];
    if (error) {
        body[@"error"] = error;
    }
    [self sendEventWithName:@"onStreamStateChanged" body:body];
}

- (void)dealloc {
    [self stopStatsTimer];
    [_rtmpClient disconnect];
    [_videoEncoder stop];
    [_audioEncoder stop];
    [_captureEngine stopPreview];
}

@end
