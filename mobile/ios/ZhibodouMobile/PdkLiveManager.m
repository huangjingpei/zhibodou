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

- (void)attachPreviewView:(PdkCameraPreviewView *)view {
    _currentPreviewView = view;
    if (_cachedSession) {
        [view setCaptureSession:_cachedSession];
    }
}

- (void)detachPreviewView:(PdkCameraPreviewView *)view {
    if (_currentPreviewView == view) {
        [view setCaptureSession:nil];
        _currentPreviewView = nil;
    }
}

- (void)attachCaptureSession:(nullable AVCaptureSession *)session {
    _cachedSession = session;
    if (_currentPreviewView) {
        [_currentPreviewView setCaptureSession:session];
    }
}

@end
