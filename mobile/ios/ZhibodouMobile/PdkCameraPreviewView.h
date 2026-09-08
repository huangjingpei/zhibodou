//
//  PdkCameraPreviewView.h
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import <UIKit/UIKit.h>
#import <AVFoundation/AVFoundation.h>

NS_ASSUME_NONNULL_BEGIN

@interface PdkCameraPreviewView : UIView

@property (nonatomic, readonly) AVCaptureVideoPreviewLayer *previewLayer;

- (void)setCaptureSession:(nullable AVCaptureSession *)session;

@end

NS_ASSUME_NONNULL_END
