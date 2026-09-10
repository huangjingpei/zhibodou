//
//  PdkCameraPreviewView.m
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import "PdkCameraPreviewView.h"
#import "PdkLiveManager.h"

@interface PdkCameraPreviewView () {
    BOOL _isFrontCamera;
}
@end

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
        _isFrontCamera = YES;
        [self commonInit];
    }
    return self;
}

- (nullable instancetype)initWithCoder:(NSCoder *)coder {
    self = [super initWithCoder:coder];
    if (self) {
        _isFrontCamera = YES;
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
    if (self.previewLayer.connection.isVideoMirroringSupported) {
        self.previewLayer.connection.videoMirrored = _isFrontCamera;
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
    if (self.previewLayer.connection.isVideoMirroringSupported) {
        self.previewLayer.connection.videoMirrored = _isFrontCamera;
    }
}

- (void)setCaptureSession:(nullable AVCaptureSession *)session {
    [self setCaptureSession:session isFrontCamera:_isFrontCamera];
}

- (void)setCaptureSession:(nullable AVCaptureSession *)session isFrontCamera:(BOOL)isFrontCamera {
    _isFrontCamera = isFrontCamera;
    dispatch_async(dispatch_get_main_queue(), ^{
        self.previewLayer.session = session;
        if (self.previewLayer.connection.isVideoOrientationSupported) {
            self.previewLayer.connection.videoOrientation = AVCaptureVideoOrientationPortrait;
        }
        if (self.previewLayer.connection.isVideoMirroringSupported) {
            self.previewLayer.connection.videoMirrored = isFrontCamera;
        }
    });
}

@end
