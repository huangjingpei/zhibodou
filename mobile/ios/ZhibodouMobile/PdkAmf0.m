//
//  PdkAmf0.m
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import "PdkAmf0.h"

typedef NS_ENUM(uint8_t, Amf0Type) {
    Amf0TypeNumber      = 0x00,
    Amf0TypeBoolean     = 0x01,
    Amf0TypeString      = 0x02,
    Amf0TypeObject      = 0x03,
    Amf0TypeNull        = 0x05,
    Amf0TypeEcmaArray   = 0x08,
    Amf0TypeObjectEnd   = 0x09,
};

@implementation PdkAmf0

+ (NSData *)encodeNumber:(double)val {
    NSMutableData *data = [NSMutableData dataWithCapacity:9];
    uint8_t type = Amf0TypeNumber;
    [data appendBytes:&type length:1];

    CFSwappedFloat64 swapped = CFConvertFloat64HostToSwapped(val);
    [data appendBytes:&swapped.v length:8];
    return data;
}

+ (NSData *)encodeBoolean:(BOOL)val {
    NSMutableData *data = [NSMutableData dataWithCapacity:2];
    uint8_t type = Amf0TypeBoolean;
    [data appendBytes:&type length:1];
    uint8_t b = val ? 1 : 0;
    [data appendBytes:&b length:1];
    return data;
}

+ (NSData *)encodeString:(NSString *)str {
    NSData *strData = [str dataUsingEncoding:NSUTF8StringEncoding];
    uint16_t len = htons((uint16_t)strData.length);

    NSMutableData *data = [NSMutableData dataWithCapacity:3 + strData.length];
    uint8_t type = Amf0TypeString;
    [data appendBytes:&type length:1];
    [data appendBytes:&len length:2];
    if (strData.length > 0) {
        [data appendData:strData];
    }
    return data;
}

+ (NSData *)encodeNull {
    uint8_t type = Amf0TypeNull;
    return [NSData dataWithBytes:&type length:1];
}

+ (NSData *)encodeObject:(NSDictionary<NSString *, id> *)dict {
    NSMutableData *data = [NSMutableData data];
    uint8_t type = Amf0TypeObject;
    [data appendBytes:&type length:1];

    [dict enumerateKeysAndObjectsUsingBlock:^(NSString *key, id obj, BOOL *stop) {
        NSData *keyData = [key dataUsingEncoding:NSUTF8StringEncoding];
        uint16_t keyLen = htons((uint16_t)keyData.length);
        [data appendBytes:&keyLen length:2];
        [data appendData:keyData];

        NSData *valData = [self encodeAny:obj];
        [data appendData:valData];
    }];

    // Object end marker: 0x00 0x00 0x09
    uint8_t endMarker[] = { 0x00, 0x00, Amf0TypeObjectEnd };
    [data appendBytes:endMarker length:3];
    return data;
}

+ (NSData *)encodeEcmaArray:(NSDictionary<NSString *, id> *)dict {
    NSMutableData *data = [NSMutableData data];
    uint8_t type = Amf0TypeEcmaArray;
    [data appendBytes:&type length:1];

    uint32_t count = htonl((uint32_t)dict.count);
    [data appendBytes:&count length:4];

    [dict enumerateKeysAndObjectsUsingBlock:^(NSString *key, id obj, BOOL *stop) {
        NSData *keyData = [key dataUsingEncoding:NSUTF8StringEncoding];
        uint16_t keyLen = htons((uint16_t)keyData.length);
        [data appendBytes:&keyLen length:2];
        [data appendData:keyData];

        NSData *valData = [self encodeAny:obj];
        [data appendData:valData];
    }];

    uint8_t endMarker[] = { 0x00, 0x00, Amf0TypeObjectEnd };
    [data appendBytes:endMarker length:3];
    return data;
}

+ (NSData *)encodeAny:(id)obj {
    if ([obj isKindOfClass:[NSString class]]) {
        return [self encodeString:(NSString *)obj];
    } else if ([obj isKindOfClass:[NSNumber class]]) {
        NSNumber *num = (NSNumber *)obj;
        if (strcmp([num objCType], @encode(BOOL)) == 0) {
            return [self encodeBoolean:[num boolValue]];
        }
        return [self encodeNumber:[num doubleValue]];
    } else if ([obj isKindOfClass:[NSDictionary class]]) {
        return [self encodeObject:(NSDictionary *)obj];
    } else if ([obj isKindOfClass:[NSNull class]] || obj == nil) {
        return [self encodeNull];
    }
    return [self encodeNull];
}

+ (nullable id)decodeValueFromData:(NSData *)data offset:(NSUInteger *)offset {
    if (*offset >= data.length) return nil;
    const uint8_t *bytes = (const uint8_t *)data.bytes;
    uint8_t type = bytes[*offset];
    (*offset)++;

    switch (type) {
        case Amf0TypeNumber: {
            if (*offset + 8 > data.length) return nil;
            CFSwappedFloat64 swapped;
            memcpy(&swapped.v, bytes + *offset, 8);
            *offset += 8;
            double val = CFConvertFloat64SwappedToHost(swapped);
            return @(val);
        }
        case Amf0TypeBoolean: {
            if (*offset + 1 > data.length) return nil;
            uint8_t b = bytes[*offset];
            (*offset)++;
            return @(b != 0);
        }
        case Amf0TypeString: {
            if (*offset + 2 > data.length) return nil;
            uint16_t len;
            memcpy(&len, bytes + *offset, 2);
            len = ntohs(len);
            *offset += 2;
            if (*offset + len > data.length) return nil;
            NSString *str = [[NSString alloc] initWithBytes:bytes + *offset
                                                     length:len
                                                   encoding:NSUTF8StringEncoding];
            *offset += len;
            return str;
        }
        case Amf0TypeObject: {
            NSMutableDictionary *dict = [NSMutableDictionary dictionary];
            while (*offset + 2 <= data.length) {
                uint16_t keyLen;
                memcpy(&keyLen, bytes + *offset, 2);
                keyLen = ntohs(keyLen);
                *offset += 2;

                if (keyLen == 0 && *offset < data.length && bytes[*offset] == Amf0TypeObjectEnd) {
                    (*offset)++; // Skip 0x09
                    break;
                }

                if (*offset + keyLen > data.length) break;
                NSString *key = [[NSString alloc] initWithBytes:bytes + *offset length:keyLen encoding:NSUTF8StringEncoding];
                *offset += keyLen;

                id val = [self decodeValueFromData:data offset:offset];
                if (key && val) {
                    dict[key] = val;
                }
            }
            return dict;
        }
        case Amf0TypeNull: {
            return [NSNull null];
        }
        default:
            return nil;
    }
}

@end
