//
//  PdkDeviceModule.m
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import "PdkDeviceModule.h"
#import "PdkKeychainHelper.h"
#import <UIKit/UIKit.h>
#import <CommonCrypto/CommonDigest.h>

static NSString * const kPdkServiceKey = @"com.zhibodou.mobile.identity";
static NSString * const kPdkDeviceIdAccount = @"persisted_device_id";

@implementation PdkDeviceModule

RCT_EXPORT_MODULE(PdkDeviceModule);

+ (BOOL)requiresMainQueueSetup {
    return YES;
}

- (NSDictionary *)constantsToExport {
    return @{
        @"deviceId": [PdkDeviceModule getStableDeviceId]
    };
}

RCT_EXPORT_BLOCKING_SYNCHRONOUS_METHOD(getDeviceIdSync) {
    return [PdkDeviceModule getStableDeviceId];
}

RCT_EXPORT_METHOD(getDeviceId:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject) {
    @try {
        resolve([PdkDeviceModule getStableDeviceId]);
    } @catch (NSException *exception) {
        reject(@"DEVICE_ID_ERR", exception.reason, nil);
    }
}

RCT_EXPORT_METHOD(setCustomDeviceId:(NSString *)customId) {
    if (customId && customId.length > 0) {
        NSString *trimmed = [customId stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
        [PdkKeychainHelper saveString:trimmed forKey:kPdkDeviceIdAccount service:kPdkServiceKey];
    }
}

RCT_EXPORT_BLOCKING_SYNCHRONOUS_METHOD(getDevConfigSync) {
    NSString *val = [[NSUserDefaults standardUserDefaults] stringForKey:@"persisted_dev_config"];
    return val ?: @"";
}

RCT_EXPORT_METHOD(getDevConfig:(RCTPromiseResolveBlock)resolve rejecter:(RCTPromiseRejectBlock)reject) {
    NSString *val = [[NSUserDefaults standardUserDefaults] stringForKey:@"persisted_dev_config"];
    resolve(val ?: @"");
}

RCT_EXPORT_METHOD(saveDevConfig:(NSString *)configJson) {
    if (configJson) {
        [[NSUserDefaults standardUserDefaults] setObject:configJson forKey:@"persisted_dev_config"];
        [[NSUserDefaults standardUserDefaults] synchronize];
    }
}

+ (NSString *)getStableDeviceId {
    static NSString *cachedId = nil;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        NSString *existing = [PdkKeychainHelper getStringForKey:kPdkDeviceIdAccount service:kPdkServiceKey];
        if (existing && existing.length > 0) {
            cachedId = existing;
            return;
        }

        NSString *idfv = [[[UIDevice currentDevice] identifierForVendor] UUIDString] ?: @"";
        NSString *model = [[UIDevice currentDevice] model] ?: @"iPhone";
        NSString *sysVer = [[UIDevice currentDevice] systemVersion] ?: @"14.0";
        NSString *rawSource = [NSString stringWithFormat:@"IOS:%@:%@:%@", idfv, model, sysVer];

        const char *cStr = [rawSource UTF8String];
        unsigned char result[CC_SHA256_DIGEST_LENGTH];
        CC_SHA256(cStr, (CC_LONG)strlen(cStr), result);

        NSMutableString *hexString = [NSMutableString stringWithCapacity:12];
        for (int i = 0; i < 6; i++) { // 12 hex chars (6 bytes)
            [hexString appendFormat:@"%02X", result[i]];
        }

        cachedId = [NSString stringWithFormat:@"MOB-IOS-%@", hexString];
        [PdkKeychainHelper saveString:cachedId forKey:kPdkDeviceIdAccount service:kPdkServiceKey];
    });
    return cachedId;
}

@end
