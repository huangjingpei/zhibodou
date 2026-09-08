//
//  PdkAudioEncoder.m
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import "PdkAudioEncoder.h"

@interface PdkAudioEncoder () {
    AudioConverterRef _audioConverter;
    dispatch_queue_t _encodeQueue;
    int _sampleRate;
    int _channels;
    int _bitrateKbps;
    int64_t _firstPtsMs;
    BOOL _hasSentAsc;
    char *_pcmBuffer;
    size_t _pcmBufferSize;
    size_t _pcmBufferCapacity;
    uint8_t *_aacBuffer;
    size_t _aacBufferSize;
}
@end

struct AudioConverterUserData {
    void *data;
    UInt32 size;
    UInt32 packetDescCount;
    AudioStreamPacketDescription *packetDescs;
};

static OSStatus AudioConverterInputDataProc(
    AudioConverterRef inAudioConverter,
    UInt32 *ioNumberDataPackets,
    AudioBufferList *ioData,
    AudioStreamPacketDescription **outDataPacketDescription,
    void *inUserData
) {
    struct AudioConverterUserData *userData = (struct AudioConverterUserData *)inUserData;
    if (userData->size == 0) {
        *ioNumberDataPackets = 0;
        return 100; // End of data / no data
    }

    ioData->mBuffers[0].mData = userData->data;
    ioData->mBuffers[0].mDataByteSize = userData->size;
    ioData->mBuffers[0].mNumberChannels = 1;

    userData->size = 0; // consumed
    return noErr;
}

@implementation PdkAudioEncoder

- (instancetype)init {
    self = [super init];
    if (self) {
        _encodeQueue = dispatch_queue_create("com.zhibodou.mobile.audioEncodeQueue", DISPATCH_QUEUE_SERIAL);
        _firstPtsMs = -1;
        _hasSentAsc = NO;
        _aacBufferSize = 2048;
        _aacBuffer = (uint8_t *)malloc(_aacBufferSize);
    }
    return self;
}

- (BOOL)prepareWithSampleRate:(int)sampleRate
                     channels:(int)channels
                  bitrateKbps:(int)bitrateKbps {
    [self stop];

    _sampleRate = sampleRate > 0 ? sampleRate : 48000;
    _channels = channels > 0 ? channels : 1;
    _bitrateKbps = bitrateKbps > 0 ? bitrateKbps : 128;
    _firstPtsMs = -1;
    _hasSentAsc = NO;

    // 1. 输入格式 (Linear PCM 16-bit)
    AudioStreamBasicDescription inDesc = {0};
    inDesc.mSampleRate = _sampleRate;
    inDesc.mFormatID = kAudioFormatLinearPCM;
    inDesc.mFormatFlags = kAudioFormatFlagIsSignedInteger | kAudioFormatFlagIsPacked;
    inDesc.mChannelsPerFrame = _channels;
    inDesc.mBitsPerChannel = 16;
    inDesc.mFramesPerPacket = 1;
    inDesc.mBytesPerFrame = inDesc.mBitsPerChannel / 8 * inDesc.mChannelsPerFrame;
    inDesc.mBytesPerPacket = inDesc.mBytesPerFrame * inDesc.mFramesPerPacket;

    // 2. 输出格式 (MPEG-4 AAC-LC)
    AudioStreamBasicDescription outDesc = {0};
    outDesc.mSampleRate = _sampleRate;
    outDesc.mFormatID = kAudioFormatMPEG4AAC;
    outDesc.mFormatFlags = kMPEG4Object_AAC_LC;
    outDesc.mChannelsPerFrame = _channels;
    outDesc.mFramesPerPacket = 1024; // AAC 恒定 1024 采样点

    OSStatus status = AudioConverterNew(&inDesc, &outDesc, &_audioConverter);
    if (status != noErr || !_audioConverter) {
        NSLog(@"[PdkAudioEncoder] AudioConverterNew failed with status: %d", (int)status);
        return NO;
    }

    // 设置编码器码率
    UInt32 bitrateBps = _bitrateKbps * 1000;
    AudioConverterSetProperty(_audioConverter, kAudioConverterEncodeBitRate, sizeof(bitrateBps), &bitrateBps);

    _isEncoding = YES;
    NSLog(@"[PdkAudioEncoder] AAC 音频硬编码器准备就绪: %d Hz, %d 声道, 码率: %d kbps", _sampleRate, _channels, _bitrateKbps);
    return YES;
}

- (NSData *)generateAudioSpecificConfigWithSampleRate:(int)sampleRate channels:(int)channels {
    // 采样率映射表
    int sampleRateIndex = 4; // 默认 44100
    switch (sampleRate) {
        case 96000: sampleRateIndex = 0; break;
        case 88200: sampleRateIndex = 1; break;
        case 64000: sampleRateIndex = 2; break;
        case 48000: sampleRateIndex = 3; break;
        case 44100: sampleRateIndex = 4; break;
        case 32000: sampleRateIndex = 5; break;
        case 24000: sampleRateIndex = 6; break;
        case 22050: sampleRateIndex = 7; break;
        case 16000: sampleRateIndex = 8; break;
        case 12000: sampleRateIndex = 9; break;
        case 11025: sampleRateIndex = 10; break;
        case 8000:  sampleRateIndex = 11; break;
        default:    sampleRateIndex = 3; break; // 48000
    }

    uint8_t asc[2];
    // 5 bits: audioObjectType (2 = AAC-LC)
    // 4 bits: sampleRateIndex
    // 4 bits: channelConfig
    // 3 bits: 0
    asc[0] = (2 << 3) | ((sampleRateIndex & 0x0E) >> 1);
    asc[1] = ((sampleRateIndex & 0x01) << 7) | ((channels & 0x0F) << 3);

    return [NSData dataWithBytes:asc length:2];
}

- (void)encodeSampleBuffer:(CMSampleBufferRef)sampleBuffer {
    if (!_isEncoding || !_audioConverter || !sampleBuffer) return;

    CMTime ptsTime = CMSampleBufferGetPresentationTimeStamp(sampleBuffer);
    int64_t currentPtsMs = (int64_t)(CMTimeGetSeconds(ptsTime) * 1000);
    if (_firstPtsMs < 0) {
        _firstPtsMs = currentPtsMs;
    }
    uint32_t relPts = (uint32_t)MAX(0, currentPtsMs - _firstPtsMs);

    // 1. 发送 AudioSpecificConfig (仅首帧)
    if (!_hasSentAsc) {
        _hasSentAsc = YES;
        NSData *asc = [self generateAudioSpecificConfigWithSampleRate:_sampleRate channels:_channels];
        [self.delegate audioEncoderDidOutputAsc:asc];
    }

    // 2. 提取 PCM 原始音频数据
    CMBlockBufferRef blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer);
    if (!blockBuffer) return;

    size_t length = 0;
    char *dataPointer = NULL;
    OSStatus status = CMBlockBufferGetDataPointer(blockBuffer, 0, NULL, &length, &dataPointer);
    if (status != noErr || !dataPointer || length <= 0) return;

    // 3. 执行硬件压缩转换
    struct AudioConverterUserData userData;
    userData.data = dataPointer;
    userData.size = (UInt32)length;
    userData.packetDescCount = 0;
    userData.packetDescs = NULL;

    AudioBufferList outBufferList;
    outBufferList.mNumberBuffers = 1;
    outBufferList.mBuffers[0].mNumberChannels = _channels;
    outBufferList.mBuffers[0].mDataByteSize = (UInt32)_aacBufferSize;
    outBufferList.mBuffers[0].mData = _aacBuffer;

    UInt32 ioOutputDataPackets = 1;
    AudioStreamPacketDescription outPacketDesc;

    status = AudioConverterFillComplexBuffer(
        _audioConverter,
        AudioConverterInputDataProc,
        &userData,
        &ioOutputDataPackets,
        &outBufferList,
        &outPacketDesc
    );

    if (status == noErr && ioOutputDataPackets > 0) {
        NSData *aacData = [NSData dataWithBytes:outBufferList.mBuffers[0].mData
                                         length:outBufferList.mBuffers[0].mDataByteSize];
        [self.delegate audioEncoderDidOutputAacData:aacData pts:relPts];
    }
}

- (void)stop {
    _isEncoding = NO;
    if (_audioConverter) {
        AudioConverterDispose(_audioConverter);
        _audioConverter = NULL;
    }
    _firstPtsMs = -1;
    _hasSentAsc = NO;
}

- (void)dealloc {
    [self stop];
    if (_aacBuffer) {
        free(_aacBuffer);
        _aacBuffer = NULL;
    }
}

@end
