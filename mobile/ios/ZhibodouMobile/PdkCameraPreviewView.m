//
//  PdkCameraPreviewView.m
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import "PdkCameraPreviewView.h"
#import "PdkLiveManager.h"

@implementation PdkCameraPreviewView

+ (Class)layerClass {
    return [AVCaptureVideoPreviewLayer class];
}

- (AVCaptureVideoPreviewLayer *)previewLayer {
    return (AVCaptureVideoPreviewLayer *)self.layer;
}

- (instancetype)initWithFrame:(CGRect)frame {
    self = [super initWithFrame:frame];
    if (self) {
        [self commonInit];
    }
    return self;
}

- (nullable instancetype)initWithCoder:(NSCoder *)coder {
    self = [super initWithCoder:coder];
    if (self) {
        [self commonInit];
    }
    return self;
}

- (void)commonInit {
    self.backgroundColor = [UIColor blackColor];
    self.clipsToBounds = YES;
    self.previewLayer.videoGravity = AVLayerVideoGravityResizeAspectFill;
    if (self.previewLayer.connection.isVideoOrientationSupported) {
        self.previewLayer.connection.videoOrientation = AVCaptureVideoOrientationPortrait;
    }
}

- (void)didMoveToWindow {
    [super didMoveToWindow];
    if (self.window) {
        [[PdkLiveManager sharedInstance] attachPreviewView:self];
    } else {
        [[PdkLiveManager sharedInstance] detachPreviewView:self];
    }
}

- (void)layoutSubviews {
    [super layoutSubviews];
    if (self.previewLayer.connection.isVideoOrientationSupported) {
        self.previewLayer.connection.videoOrientation = AVCaptureVideoOrientationPortrait;
    }
}

- (void)setCaptureSession:(nullable AVCaptureSession *)session {
    dispatch_async(dispatch_get_main_queue(), ^{
        self.previewLayer.session = session;
        if (self.previewLayer.connection.isVideoOrientationSupported) {
            self.previewLayer.connection.videoOrientation = AVCaptureVideoOrientationPortrait;
        }
    });
}

@end
