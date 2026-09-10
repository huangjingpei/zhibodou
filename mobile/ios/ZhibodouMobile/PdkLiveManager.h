//
//  PdkLiveManager.h
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import <Foundation/Foundation.h>
#import <AVFoundation/AVFoundation.h>

NS_ASSUME_NONNULL_BEGIN

@class PdkCameraPreviewView;
@class PdkLiveModule;

@interface PdkLiveManager : NSObject

@property (nonatomic, weak, nullable) PdkCameraPreviewView *currentPreviewView;
@property (nonatomic, weak, nullable) PdkLiveModule *currentLiveModule;
@property (nonatomic, assign) BOOL isFrontCamera;

+ (instancetype)sharedInstance;

- (void)attachPreviewView:(PdkCameraPreviewView *)view;
- (void)detachPreviewView:(PdkCameraPreviewView *)view;

- (void)attachCaptureSession:(nullable AVCaptureSession *)session;
- (void)attachCaptureSession:(nullable AVCaptureSession *)session isFrontCamera:(BOOL)isFrontCamera;

@end

NS_ASSUME_NONNULL_END
