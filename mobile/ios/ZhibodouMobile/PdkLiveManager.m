//
//  PdkLiveManager.m
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import "PdkLiveManager.h"
#import "PdkCameraPreviewView.h"

@interface PdkLiveManager ()
@property (nonatomic, strong, nullable) AVCaptureSession *cachedSession;
@end

@implementation PdkLiveManager

+ (instancetype)sharedInstance {
    static PdkLiveManager *instance = nil;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        instance = [[PdkLiveManager alloc] init];
    });
    return instance;
}

- (instancetype)init {
    self = [super init];
    if (self) {
        _isFrontCamera = YES;
    }
    return self;
}

- (void)attachPreviewView:(PdkCameraPreviewView *)view {
    _currentPreviewView = view;
    if (_cachedSession) {
        [view setCaptureSession:_cachedSession isFrontCamera:_isFrontCamera];
    }
}

- (void)detachPreviewView:(PdkCameraPreviewView *)view {
    if (_currentPreviewView == view) {
        [view setCaptureSession:nil isFrontCamera:_isFrontCamera];
        _currentPreviewView = nil;
    }
}

- (void)attachCaptureSession:(nullable AVCaptureSession *)session isFrontCamera:(BOOL)isFrontCamera {
    _cachedSession = session;
    _isFrontCamera = isFrontCamera;
    if (_currentPreviewView) {
        [_currentPreviewView setCaptureSession:session isFrontCamera:isFrontCamera];
    }
}

- (void)attachCaptureSession:(nullable AVCaptureSession *)session {
    [self attachCaptureSession:session isFrontCamera:_isFrontCamera];
}

@end
