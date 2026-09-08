//
//  PdkDeviceModule.h
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import <Foundation/Foundation.h>
#import <React/RCTBridgeModule.h>

NS_ASSUME_NONNULL_BEGIN

@interface PdkDeviceModule : NSObject <RCTBridgeModule>

+ (NSString *)getStableDeviceId;

@end

NS_ASSUME_NONNULL_END
