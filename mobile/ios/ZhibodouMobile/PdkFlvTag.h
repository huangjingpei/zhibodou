//
//  PdkFlvTag.h
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

@interface PdkFlvTag : NSObject

+ (NSData *)createAvcSequenceHeaderWithSps:(NSData *)sps pps:(NSData *)pps;

+ (NSData *)createVideoTagWithNaluData:(NSData *)naluData
                                   pts:(uint32_t)pts
                                   dts:(uint32_t)dts
                            isKeyframe:(BOOL)isKeyframe;

+ (NSData *)createAacSequenceHeaderWithAsc:(NSData *)asc;

+ (NSData *)createAudioTagWithAacData:(NSData *)aacData;

@end

NS_ASSUME_NONNULL_END
