//
//  PdkRtmpClient.h
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

@protocol PdkRtmpClientDelegate <NSObject>

- (void)rtmpClientDidConnect;
- (void)rtmpClientDidFailWithError:(NSString *)error;
- (void)rtmpClientDidDisconnect;
- (void)rtmpClientDidUpdateBitrate:(uint32_t)bitrateBps;

@end

@interface PdkRtmpClient : NSObject

@property (nonatomic, weak) id<PdkRtmpClientDelegate> delegate;
@property (nonatomic, readonly) BOOL isConnected;
@property (nonatomic, readonly) BOOL isConnecting;

- (BOOL)connectWithUrl:(NSString *)url
                 width:(int)width
                height:(int)height
                   fps:(int)fps
           bitrateKbps:(int)bitrateKbps
      audioBitrateKbps:(int)audioBitrateKbps
            sampleRate:(int)sampleRate;

- (void)sendVideoHeaderWithSps:(NSData *)sps pps:(NSData *)pps;
- (void)sendVideoData:(NSData *)naluData pts:(uint32_t)pts dts:(uint32_t)dts isKeyframe:(BOOL)isKeyframe;

- (void)sendAudioHeaderWithAsc:(NSData *)asc;
- (void)sendAudioData:(NSData *)aacData pts:(uint32_t)pts;

- (void)disconnect;

@end

NS_ASSUME_NONNULL_END
