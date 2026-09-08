//
//  PdkAudioEncoder.h
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import <Foundation/Foundation.h>
#import <AVFoundation/AVFoundation.h>
#import <AudioToolbox/AudioToolbox.h>

NS_ASSUME_NONNULL_BEGIN

@protocol PdkAudioEncoderDelegate <NSObject>

- (void)audioEncoderDidOutputAsc:(NSData *)asc;
- (void)audioEncoderDidOutputAacData:(NSData *)aacData pts:(uint32_t)pts;

@end

@interface PdkAudioEncoder : NSObject

@property (nonatomic, weak) id<PdkAudioEncoderDelegate> delegate;
@property (nonatomic, readonly) BOOL isEncoding;

- (BOOL)prepareWithSampleRate:(int)sampleRate
                     channels:(int)channels
                  bitrateKbps:(int)bitrateKbps;

- (void)encodeSampleBuffer:(CMSampleBufferRef)sampleBuffer;

- (void)stop;

@end

NS_ASSUME_NONNULL_END
