//
//  PdkCameraViewManager.m
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import "PdkCameraViewManager.h"
#import "PdkCameraPreviewView.h"

@implementation PdkCameraViewManager

RCT_EXPORT_MODULE(PdkCameraView);

- (UIView *)view {
    return [[PdkCameraPreviewView alloc] initWithFrame:CGRectZero];
}

+ (BOOL)requiresMainQueueSetup {
    return YES;
}

@end
