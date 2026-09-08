//
//  PdkVideoEncoder.h
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
#import <AVFoundation/AVFoundation.h>

NS_ASSUME_NONNULL_BEGIN

@protocol PdkVideoEncoderDelegate <NSObject>

- (void)videoEncoderDidOutputSps:(NSData *)sps pps:(NSData *)pps;
- (void)videoEncoderDidOutputNaluData:(NSData *)naluData
                                  pts:(uint32_t)pts
                                  dts:(uint32_t)dts
                           isKeyframe:(BOOL)isKeyframe;

@end

@interface PdkVideoEncoder : NSObject

@property (nonatomic, weak) id<PdkVideoEncoderDelegate> delegate;
@property (nonatomic, readonly) BOOL isEncoding;

- (BOOL)prepareWithWidth:(int)width
                  height:(int)height
                     fps:(int)fps
             bitrateKbps:(int)bitrateKbps;

- (void)encodeSampleBuffer:(CMSampleBufferRef)sampleBuffer;

- (void)setBitrate:(int)bitrateKbps;

- (void)stop;

@end

NS_ASSUME_NONNULL_END
