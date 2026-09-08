//
//  PdkFlvTag.m
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import "PdkFlvTag.h"

@implementation PdkFlvTag

+ (NSData *)createAvcSequenceHeaderWithSps:(NSData *)sps pps:(NSData *)pps {
    if (sps.length < 4 || pps.length < 1) return [NSData data];

    NSMutableData *tag = [NSMutableData data];

    // 1. FLV Video Tag Header: KeyFrame (0x10) + AVC (0x07) = 0x17
    uint8_t header[] = {
        0x17,       // FrameType: 1 (KeyFrame), CodecID: 7 (AVC)
        0x00,       // AVCPacketType: 0 (AVC Sequence Header)
        0x00, 0x00, 0x00 // CompositionTime: 0
    };
    [tag appendBytes:header length:5];

    // 2. AVCDecoderConfigurationRecord
    const uint8_t *spsBytes = (const uint8_t *)sps.bytes;
    uint8_t cfgHeader[] = {
        0x01,                   // configurationVersion: 1
        spsBytes[1],            // AVCProfileIndication
        spsBytes[2],            // profile_compatibility
        spsBytes[3],            // AVCLevelIndication
        0xFF,                   // 6 bits reserved (111111) + lengthSizeMinusOne (3 -> 4 bytes)
        0xE1                    // 3 bits reserved (111) + numOfSequenceParameterSets (1)
    };
    [tag appendBytes:cfgHeader length:6];

    // SPS length (2 bytes big endian) + SPS
    uint16_t spsLen = htons((uint16_t)sps.length);
    [tag appendBytes:&spsLen length:2];
    [tag appendData:sps];

    // PPS count (1) + PPS length (2 bytes big endian) + PPS
    uint8_t ppsCount = 1;
    [tag appendBytes:&ppsCount length:1];
    uint16_t ppsLen = htons((uint16_t)pps.length);
    [tag appendBytes:&ppsLen length:2];
    [tag appendData:pps];

    return tag;
}

+ (NSData *)createVideoTagWithNaluData:(NSData *)naluData
                                   pts:(uint32_t)pts
                                   dts:(uint32_t)dts
                            isKeyframe:(BOOL)isKeyframe {
    NSMutableData *tag = [NSMutableData dataWithCapacity:5 + naluData.length];

    // FrameType: 1 (KeyFrame = 0x10) 或 2 (InterFrame = 0x20) + CodecID: 7 (AVC)
    uint8_t frameType = isKeyframe ? 0x17 : 0x27;
    uint8_t packetType = 0x01; // AVCPacketType: 1 (AVC NALU)

    // Composition Time = PTS - DTS (24 bits big-endian)
    int32_t compTime = (int32_t)(pts - dts);
    uint8_t ctBytes[3];
    ctBytes[0] = (compTime >> 16) & 0xFF;
    ctBytes[1] = (compTime >> 8) & 0xFF;
    ctBytes[2] = compTime & 0xFF;

    [tag appendBytes:&frameType length:1];
    [tag appendBytes:&packetType length:1];
    [tag appendBytes:ctBytes length:3];

    // NALU 数据 (VideoToolbox 已经输出标准的 4 字节大端长度前缀)
    if (naluData.length > 0) {
        [tag appendData:naluData];
    }

    return tag;
}

+ (NSData *)createAacSequenceHeaderWithAsc:(NSData *)asc {
    NSMutableData *tag = [NSMutableData data];

    // SoundFormat: 10 (AAC), SoundRate: 3 (44k/48k), SoundSize: 1 (16-bit), SoundType: 1 (Stereo) = 0xAF
    uint8_t audioHeader[] = {
        0xAF,
        0x00 // AACPacketType: 0 (AAC sequence header)
    };
    [tag appendBytes:audioHeader length:2];
    [tag appendData:asc];

    return tag;
}

+ (NSData *)createAudioTagWithAacData:(NSData *)aacData {
    NSMutableData *tag = [NSMutableData dataWithCapacity:2 + aacData.length];

    uint8_t audioHeader[] = {
        0xAF,
        0x01 // AACPacketType: 1 (AAC raw)
    };
    [tag appendBytes:audioHeader length:2];
    [tag appendData:aacData];

    return tag;
}

@end
