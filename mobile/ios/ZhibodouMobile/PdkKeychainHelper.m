//
//  PdkKeychainHelper.m
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import "PdkKeychainHelper.h"

@implementation PdkKeychainHelper

+ (NSMutableDictionary *)keychainQueryForKey:(NSString *)key service:(NSString *)service {
    return [NSMutableDictionary dictionaryWithDictionary:@{
        (__bridge id)kSecClass: (__bridge id)kSecClassGenericPassword,
        (__bridge id)kSecAttrService: service ?: @"com.zhibodou.mobile.identity",
        (__bridge id)kSecAttrAccount: key,
        (__bridge id)kSecAttrAccessible: (__bridge id)kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
    }];
}

+ (BOOL)saveString:(NSString *)string forKey:(NSString *)key service:(NSString *)service {
    if (!string || !key) return NO;
    NSData *data = [string dataUsingEncoding:NSUTF8StringEncoding];
    if (!data) return NO;

    NSMutableDictionary *query = [self keychainQueryForKey:key service:service];

    // Check if existing item exists
    OSStatus checkStatus = SecItemCopyMatching((__bridge CFDictionaryRef)query, NULL);
    if (checkStatus == errSecSuccess) {
        NSMutableDictionary *attributesToUpdate = [NSMutableDictionary dictionaryWithObject:data
                                                                                     forKey:(__bridge id)kSecValueData];
        OSStatus updateStatus = SecItemUpdate((__bridge CFDictionaryRef)query, (__bridge CFDictionaryRef)attributesToUpdate);
        return updateStatus == errSecSuccess;
    } else {
        [query setObject:data forKey:(__bridge id)kSecValueData];
        OSStatus addStatus = SecItemAdd((__bridge CFDictionaryRef)query, NULL);
        return addStatus == errSecSuccess;
    }
}

+ (nullable NSString *)getStringForKey:(NSString *)key service:(NSString *)service {
    if (!key) return nil;

    NSMutableDictionary *query = [self keychainQueryForKey:key service:service];
    [query setObject:(__bridge id)kCFBooleanTrue forKey:(__bridge id)kSecReturnData];
    [query setObject:(__bridge id)kSecMatchLimitOne forKey:(__bridge id)kSecMatchLimit];

    CFTypeRef result = NULL;
    OSStatus status = SecItemCopyMatching((__bridge CFDictionaryRef)query, &result);
    if (status == errSecSuccess && result != NULL) {
        NSData *data = (__bridge_transfer NSData *)result;
        return [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
    }
    if (result != NULL) {
        CFRelease(result);
    }
    return nil;
}

+ (BOOL)deleteKey:(NSString *)key service:(NSString *)service {
    if (!key) return NO;
    NSMutableDictionary *query = [self keychainQueryForKey:key service:service];
    OSStatus status = SecItemDelete((__bridge CFDictionaryRef)query);
    return (status == errSecSuccess || status == errSecItemNotFound);
}

@end
