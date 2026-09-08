//
//  PdkKeychainHelper.h
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import <Foundation/Foundation.h>
#import <Security/Security.h>

NS_ASSUME_NONNULL_BEGIN

@interface PdkKeychainHelper : NSObject

+ (BOOL)saveString:(NSString *)string forKey:(NSString *)key service:(NSString *)service;
+ (nullable NSString *)getStringForKey:(NSString *)key service:(NSString *)service;
+ (BOOL)deleteKey:(NSString *)key service:(NSString *)service;

@end

NS_ASSUME_NONNULL_END
