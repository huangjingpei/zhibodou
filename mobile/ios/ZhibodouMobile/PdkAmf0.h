//
//  PdkAmf0.h
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

@interface PdkAmf0 : NSObject

+ (NSData *)encodeNumber:(double)val;
+ (NSData *)encodeBoolean:(BOOL)val;
+ (NSData *)encodeString:(NSString *)str;
+ (NSData *)encodeNull;
+ (NSData *)encodeObject:(NSDictionary<NSString *, id> *)dict;
+ (NSData *)encodeEcmaArray:(NSDictionary<NSString *, id> *)dict;

+ (nullable id)decodeValueFromData:(NSData *)data offset:(NSUInteger *)offset;

@end

NS_ASSUME_NONNULL_END
