//
//  PdkCaptureEngine.h
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import <Foundation/Foundation.h>
#import <AVFoundation/AVFoundation.h>

NS_ASSUME_NONNULL_BEGIN

@protocol PdkCaptureEngineDelegate <NSObject>

- (void)captureEngineDidOutputVideoSampleBuffer:(CMSampleBufferRef)sampleBuffer;
- (void)captureEngineDidOutputAudioSampleBuffer:(CMSampleBufferRef)sampleBuffer;

@end

@interface PdkCaptureEngine : NSObject

@property (nonatomic, weak) id<PdkCaptureEngineDelegate> delegate;
@property (nonatomic, readonly) AVCaptureSession *captureSession;
@property (nonatomic, readonly) BOOL isRunning;
@property (nonatomic, readonly) BOOL isInterrupted;
@property (nonatomic, readonly) BOOL isFrontCamera;
@property (nonatomic, readonly) BOOL isMuted;
@property (nonatomic, readonly) BOOL isTorchOn;

- (BOOL)startPreviewWithFront:(BOOL)isFront fps:(int)fps;
- (void)stopPreview;
- (BOOL)recoverSession;

- (BOOL)switchCamera;
- (BOOL)toggleTorch:(BOOL)enable;
- (BOOL)setMuted:(BOOL)muted;

@end

NS_ASSUME_NONNULL_END
