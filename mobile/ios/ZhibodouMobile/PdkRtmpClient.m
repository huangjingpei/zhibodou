//
//  PdkRtmpClient.m
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import "PdkRtmpClient.h"
#import "PdkAmf0.h"
#import "PdkFlvTag.h"
#import <sys/socket.h>
#import <netinet/in.h>
#import <arpa/inet.h>
#import <netdb.h>
#import <unistd.h>
#import <Security/SecureTransport.h>

#define RTMP_OUT_CHUNK_SIZE 4096

typedef NS_ENUM(uint8_t, RtmpMessageType) {
    RtmpMsgSetChunkSize     = 0x01,
    RtmpMsgAbort            = 0x02,
    RtmpMsgAck              = 0x03,
    RtmpMsgUserControl      = 0x04,
    RtmpMsgWindowAckSize    = 0x05,
    RtmpMsgSetPeerBandwidth = 0x06,
    RtmpMsgAudio            = 0x08,
    RtmpMsgVideo            = 0x09,
    RtmpMsgDataAmf0         = 0x12, // 18
    RtmpMsgCommandAmf0      = 0x14, // 20
};

@interface PdkRtmpClient () {
    int _socketFd;
    BOOL _isTls;
    SSLContextRef _sslContext;
    dispatch_queue_t _socketQueue;
    dispatch_source_t _bitrateTimer;
    uint32_t _streamId;
    uint32_t _bytesSentSinceLastCheck;
    uint32_t _currentBitrateBps;
    BOOL _isConnected;
    BOOL _isConnecting;

    NSString *_host;
    int _port;
    NSString *_appName;
    NSString *_streamKey;
    NSString *_tcUrl;

    int _width;
    int _height;
    int _fps;
    int _videoBitrateKbps;
    int _audioBitrateKbps;
    int _sampleRate;

    NSData *_cachedSps;
    NSData *_cachedPps;
    NSData *_cachedAsc;
}
@end

static OSStatus SocketSSLRead(SSLConnectionRef connection, void *data, size_t *dataLength) {
    int fd = (int)(intptr_t)connection;
    size_t bytesToRead = *dataLength;
    ssize_t bytesRead = recv(fd, data, bytesToRead, 0);
    if (bytesRead > 0) {
        *dataLength = (size_t)bytesRead;
        return noErr;
    } else if (bytesRead == 0) {
        *dataLength = 0;
        return errSSLClosedGraceful;
    } else {
        *dataLength = 0;
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
            return errSSLWouldBlock;
        }
        return errSecIO;
    }
}

static OSStatus SocketSSLWrite(SSLConnectionRef connection, const void *data, size_t *dataLength) {
    int fd = (int)(intptr_t)connection;
    size_t bytesToWrite = *dataLength;
    ssize_t bytesWritten = send(fd, data, bytesToWrite, 0);
    if (bytesWritten > 0) {
        *dataLength = (size_t)bytesWritten;
        return noErr;
    } else {
        *dataLength = 0;
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
            return errSSLWouldBlock;
        }
        return errSecIO;
    }
}

@implementation PdkRtmpClient

- (instancetype)init {
    self = [super init];
    if (self) {
        _socketFd = -1;
        _isTls = NO;
        _sslContext = NULL;
        _streamId = 1;
        _socketQueue = dispatch_queue_create("com.zhibodou.mobile.rtmpSocketQueue", DISPATCH_QUEUE_SERIAL);
    }
    return self;
}

- (BOOL)isConnected {
    return _isConnected;
}

- (BOOL)isConnecting {
    return _isConnecting;
}

- (BOOL)parseRtmpUrl:(NSString *)url {
    // 格式: rtmp://host[:port]/app/streamKey 或 rtmps://host[:port]/app/streamKey (TLS 加密)
    BOOL isTls = NO;
    NSString *withoutScheme = nil;
    int defaultPort = 1935;

    if ([url hasPrefix:@"rtmps://"]) {
        isTls = YES;
        withoutScheme = [url substringFromIndex:8];
        defaultPort = 443;
    } else if ([url hasPrefix:@"rtmp://"]) {
        isTls = NO;
        withoutScheme = [url substringFromIndex:7];
        defaultPort = 1935;
    } else {
        return NO;
    }

    _isTls = isTls;
    NSRange firstSlash = [withoutScheme rangeOfString:@"/"];
    if (firstSlash.location == NSNotFound) return NO;

    NSString *hostPort = [withoutScheme substringToIndex:firstSlash.location];
    NSString *path = [withoutScheme substringFromIndex:firstSlash.location + 1];

    NSArray *hostPortParts = [hostPort componentsSeparatedByString:@":"];
    _host = hostPortParts[0];
    _port = hostPortParts.count > 1 ? [hostPortParts[1] intValue] : defaultPort;

    NSArray *pathParts = [path componentsSeparatedByString:@"/"];
    if (pathParts.count < 2) {
        _appName = path;
        _streamKey = @"live";
    } else {
        _appName = pathParts[0];
        _streamKey = [path substringFromIndex:_appName.length + 1];
    }

    _tcUrl = [NSString stringWithFormat:@"%@://%@:%d/%@", _isTls ? @"rtmps" : @"rtmp", _host, _port, _appName];
    return YES;
}

- (BOOL)connectWithUrl:(NSString *)url
                 width:(int)width
                height:(int)height
                   fps:(int)fps
           bitrateKbps:(int)bitrateKbps
      audioBitrateKbps:(int)audioBitrateKbps
            sampleRate:(int)sampleRate {
    if (_isConnected || _isConnecting) {
        [self disconnect];
    }

    if (![self parseRtmpUrl:url]) {
        [self.delegate rtmpClientDidFailWithError:@"非法 RTMP/RTMPS 地址格式"];
        return NO;
    }

    _width = width;
    _height = height;
    _fps = fps;
    _videoBitrateKbps = bitrateKbps;
    _audioBitrateKbps = audioBitrateKbps;
    _sampleRate = sampleRate;
    _isConnecting = YES;

    dispatch_async(_socketQueue, ^{
        [self performConnectionPipeline];
    });

    return YES;
}

- (void)performConnectionPipeline {
    NSLog(@"[PdkRtmpClient] 正在连接 %@ 服务器: %@:%d (App: %@, StreamKey: %@)",
          self->_isTls ? @"RTMPS (TLS 加密)" : @"RTMP", self->_host, self->_port, self->_appName, self->_streamKey);

    // 1. DNS 解析与 Socket 创建
    struct addrinfo hints, *res;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;

    char portStr[16];
    snprintf(portStr, sizeof(portStr), "%d", _port);

    int err = getaddrinfo([_host UTF8String], portStr, &hints, &res);
    if (err != 0 || !res) {
        [self notifyError:[NSString stringWithFormat:@"DNS 解析失败: %s", gai_strerror(err)]];
        return;
    }

    _socketFd = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
    if (_socketFd < 0) {
        freeaddrinfo(res);
        [self notifyError:@"创建 Socket 失败"];
        return;
    }

    // 设置超时 5 秒与抗 SIGPIPE
    struct timeval tv;
    tv.tv_sec = 5;
    tv.tv_usec = 0;
    setsockopt(_socketFd, SOL_SOCKET, SO_RCVTIMEO, (const char *)&tv, sizeof(tv));
    setsockopt(_socketFd, SOL_SOCKET, SO_SNDTIMEO, (const char *)&tv, sizeof(tv));
    int nosigpipe = 1;
    setsockopt(_socketFd, SOL_SOCKET, SO_NOSIGPIPE, &nosigpipe, sizeof(nosigpipe));

    // 2. TCP 握手
    if (connect(_socketFd, res->ai_addr, res->ai_addrlen) < 0) {
        freeaddrinfo(res);
        [self notifyError:@"TCP 连接服务器失败"];
        return;
    }
    freeaddrinfo(res);

    // 2.1 若为 RTMPS，建立 TLS/SSL 传输加密通道
    if (_isTls) {
        NSLog(@"[PdkRtmpClient] 正在协商 RTMPS TLS/SSL 安全握手...");
        _sslContext = SSLCreateContext(kCFAllocatorDefault, kSSLClientSide, kSSLStreamType);
        if (!_sslContext) {
            [self notifyError:@"创建 TLS SSLContext 失败"];
            return;
        }

        SSLSetIOFuncs(_sslContext, SocketSSLRead, SocketSSLWrite);
        SSLSetConnection(_sslContext, (SSLConnectionRef)(intptr_t)_socketFd);
        SSLSetPeerDomainName(_sslContext, [_host UTF8String], strlen([_host UTF8String]));

        OSStatus sslStatus;
        do {
            sslStatus = SSLHandshake(_sslContext);
        } while (sslStatus == errSSLWouldBlock);

        if (sslStatus != noErr) {
            [self notifyError:[NSString stringWithFormat:@"RTMPS TLS 握手失败 (代码: %d)", (int)sslStatus]];
            return;
        }
        NSLog(@"[PdkRtmpClient] RTMPS TLS/SSL 传输安全加密链路建立成功！");
    }

    // 3. RTMP 握手协议 (C0/C1 -> S0/S1/S2 -> C2)
    if (![self performRtmpHandshake]) {
        [self notifyError:@"RTMP 协议握手失败"];
        return;
    }

    // 4. 发送 Set Chunk Size (4096)
    [self sendSetChunkSize:RTMP_OUT_CHUNK_SIZE];

    // 5. 发送 connect RPC 指令
    [self sendConnectCommand];

    // 6. 接收并验证 connect 响应 (_result)
    if (![self readConnectResponse]) {
        [self notifyError:@"RTMP connect 握手认证失败"];
        return;
    }

    // 7. 发送 releaseStream & FCPublish & createStream
    [self sendReleaseStreamCommand];
    [self sendFCPublishCommand];
    [self sendCreateStreamCommand];

    // 8. 接收 createStream 响应并获取 streamId
    if (![self readCreateStreamResponse]) {
        [self notifyError:@"创建推流会话 (createStream) 失败"];
        return;
    }

    // 9. 发送 publish 指令
    [self sendPublishCommand];

    // 10. 发送 @setDataFrame onMetaData 元数据
    [self sendMetaData];

    _isConnected = YES;
    _isConnecting = NO;
    NSLog(@"[PdkRtmpClient] RTMP%@ 推流通道成功建立，开始音视频传输！", self->_isTls ? @"S (加密)" : @"");

    [self startBitrateTimer];

    // 补发缓存的序列头
    if (_cachedSps && _cachedPps) {
        [self sendVideoHeaderWithSps:_cachedSps pps:_cachedPps];
    }
    if (_cachedAsc) {
        [self sendAudioHeaderWithAsc:_cachedAsc];
    }

    dispatch_async(dispatch_get_main_queue(), ^{
        [self.delegate rtmpClientDidConnect];
    });
}

- (BOOL)performRtmpHandshake {
    // 构造 C0 (1 字节 0x03) + C1 (1536 字节)
    uint8_t c0c1[1537];
    c0c1[0] = 0x03; // RTMP 版本号
    uint32_t uptime = htonl((uint32_t)([[NSProcessInfo processInfo] systemUptime] * 1000));
    memcpy(c0c1 + 1, &uptime, 4);
    memset(c0c1 + 5, 0, 4); // Zero
    for (int i = 9; i < 1537; i++) {
        c0c1[i] = (uint8_t)(arc4random_uniform(256));
    }

    if (![self sendExactBytes:c0c1 length:1537]) return NO;

    // 接收 S0 (1 字节) + S1 (1536 字节) + S2 (1536 字节) = 3073 字节
    uint8_t s0s1s2[3073];
    if (![self readExactBytes:s0s1s2 length:3073]) return NO;

    if (s0s1s2[0] != 0x03) {
        NSLog(@"[PdkRtmpClient] 不支持的 RTMP 服务端版本: %d", s0s1s2[0]);
        return NO;
    }

    // 发送 C2 (1536 字节，回显 S1)
    uint8_t *s1 = s0s1s2 + 1;
    if (![self sendExactBytes:s1 length:1536]) return NO;

    return YES;
}

- (void)sendSetChunkSize:(uint32_t)chunkSize {
    NSMutableData *payload = [NSMutableData dataWithCapacity:4];
    uint32_t val = htonl(chunkSize);
    [payload appendBytes:&val length:4];

    [self sendPacketWithCsid:2
                     typeId:RtmpMsgSetChunkSize
                   streamId:0
                  timestamp:0
                    payload:payload];
}

- (void)sendConnectCommand {
    NSMutableData *payload = [NSMutableData data];
    [payload appendData:[PdkAmf0 encodeString:@"connect"]];
    [payload appendData:[PdkAmf0 encodeNumber:1.0]]; // Transaction ID

    NSDictionary *cmdObj = @{
        @"app": _appName ?: @"live",
        @"flashVer": @"FMLE/3.0 (compatible; Zhibodou-iOS)",
        @"tcUrl": _tcUrl ?: @"",
        @"fpad": @(NO),
        @"capabilities": @(15.0),
        @"audioCodecs": @(0x0400), // AAC
        @"videoCodecs": @(0x0080), // H.264
        @"videoFunction": @(1.0)
    };
    [payload appendData:[PdkAmf0 encodeObject:cmdObj]];

    [self sendPacketWithCsid:3
                     typeId:RtmpMsgCommandAmf0
                   streamId:0
                  timestamp:0
                    payload:payload];
}

- (BOOL)readConnectResponse {
    // 读取 RTMP 数据块，等待针对 connect(1.0) 的 _result 响应
    uint8_t buffer[2048];
    ssize_t received = [self readSomeBytes:buffer length:sizeof(buffer)];
    return received > 0;
}

- (void)sendReleaseStreamCommand {
    NSMutableData *payload = [NSMutableData data];
    [payload appendData:[PdkAmf0 encodeString:@"releaseStream"]];
    [payload appendData:[PdkAmf0 encodeNumber:2.0]];
    [payload appendData:[PdkAmf0 encodeNull]];
    [payload appendData:[PdkAmf0 encodeString:_streamKey]];

    [self sendPacketWithCsid:3 typeId:RtmpMsgCommandAmf0 streamId:0 timestamp:0 payload:payload];
}

- (void)sendFCPublishCommand {
    NSMutableData *payload = [NSMutableData data];
    [payload appendData:[PdkAmf0 encodeString:@"FCPublish"]];
    [payload appendData:[PdkAmf0 encodeNumber:3.0]];
    [payload appendData:[PdkAmf0 encodeNull]];
    [payload appendData:[PdkAmf0 encodeString:_streamKey]];

    [self sendPacketWithCsid:3 typeId:RtmpMsgCommandAmf0 streamId:0 timestamp:0 payload:payload];
}

- (void)sendCreateStreamCommand {
    NSMutableData *payload = [NSMutableData data];
    [payload appendData:[PdkAmf0 encodeString:@"createStream"]];
    [payload appendData:[PdkAmf0 encodeNumber:4.0]];
    [payload appendData:[PdkAmf0 encodeNull]];

    [self sendPacketWithCsid:3 typeId:RtmpMsgCommandAmf0 streamId:0 timestamp:0 payload:payload];
}

- (BOOL)readCreateStreamResponse {
    uint8_t buffer[2048];
    ssize_t received = [self readSomeBytes:buffer length:sizeof(buffer)];
    if (received <= 0) return NO;

    _streamId = 1;
    return YES;
}

- (void)sendPublishCommand {
    NSMutableData *payload = [NSMutableData data];
    [payload appendData:[PdkAmf0 encodeString:@"publish"]];
    [payload appendData:[PdkAmf0 encodeNumber:5.0]];
    [payload appendData:[PdkAmf0 encodeNull]];
    [payload appendData:[PdkAmf0 encodeString:_streamKey]];
    [payload appendData:[PdkAmf0 encodeString:@"live"]];

    [self sendPacketWithCsid:8 typeId:RtmpMsgCommandAmf0 streamId:_streamId timestamp:0 payload:payload];
}

- (void)sendMetaData {
    NSMutableData *payload = [NSMutableData data];
    [payload appendData:[PdkAmf0 encodeString:@"@setDataFrame"]];
    [payload appendData:[PdkAmf0 encodeString:@"onMetaData"]];

    NSDictionary *meta = @{
        @"width": @(_width),
        @"height": @(_height),
        @"framerate": @(_fps),
        @"videocodecid": @(7.0), // AVC
        @"videodatarate": @(_videoBitrateKbps),
        @"audiocodecid": @(10.0), // AAC
        @"audiodatarate": @(_audioBitrateKbps),
        @"audiosamplerate": @(_sampleRate),
        @"stereo": @(YES)
    };
    [payload appendData:[PdkAmf0 encodeEcmaArray:meta]];

    [self sendPacketWithCsid:4 typeId:RtmpMsgDataAmf0 streamId:_streamId timestamp:0 payload:payload];
}

#pragma mark - 音视频发送

- (void)sendVideoHeaderWithSps:(NSData *)sps pps:(NSData *)pps {
    _cachedSps = sps;
    _cachedPps = pps;
    if (!_isConnected) return;

    dispatch_async(_socketQueue, ^{
        NSData *headerTag = [PdkFlvTag createAvcSequenceHeaderWithSps:sps pps:pps];
        [self sendPacketWithCsid:6 typeId:RtmpMsgVideo streamId:self->_streamId timestamp:0 payload:headerTag];
    });
}

- (void)sendVideoData:(NSData *)naluData pts:(uint32_t)pts dts:(uint32_t)dts isKeyframe:(BOOL)isKeyframe {
    if (!_isConnected || naluData.length == 0) return;

    dispatch_async(_socketQueue, ^{
        NSData *videoTag = [PdkFlvTag createVideoTagWithNaluData:naluData pts:pts dts:dts isKeyframe:isKeyframe];
        [self sendPacketWithCsid:6 typeId:RtmpMsgVideo streamId:self->_streamId timestamp:dts payload:videoTag];
    });
}

- (void)sendAudioHeaderWithAsc:(NSData *)asc {
    _cachedAsc = asc;
    if (!_isConnected) return;

    dispatch_async(_socketQueue, ^{
        NSData *headerTag = [PdkFlvTag createAacSequenceHeaderWithAsc:asc];
        [self sendPacketWithCsid:7 typeId:RtmpMsgAudio streamId:self->_streamId timestamp:0 payload:headerTag];
    });
}

- (void)sendAudioData:(NSData *)aacData pts:(uint32_t)pts {
    if (!_isConnected || aacData.length == 0) return;

    dispatch_async(_socketQueue, ^{
        NSData *audioTag = [PdkFlvTag createAudioTagWithAacData:aacData];
        [self sendPacketWithCsid:7 typeId:RtmpMsgAudio streamId:self->_streamId timestamp:pts payload:audioTag];
    });
}

#pragma mark - RTMP Chunk 封装与发送

- (void)sendPacketWithCsid:(uint8_t)csid
                    typeId:(uint8_t)typeId
                  streamId:(uint32_t)streamId
                 timestamp:(uint32_t)timestamp
                   payload:(NSData *)payload {
    if (_socketFd < 0) return;

    uint32_t length = (uint32_t)payload.length;
    const uint8_t *bytes = (const uint8_t *)payload.bytes;

    // 1. 第一个 Chunk: Type 0 Header (11 字节)
    NSMutableData *chunkData = [NSMutableData dataWithCapacity:12 + MIN(length, RTMP_OUT_CHUNK_SIZE)];
    uint8_t fmt = 0x00; // Type 0
    uint8_t basicHeader = (fmt << 6) | (csid & 0x3F);
    [chunkData appendBytes:&basicHeader length:1];

    uint8_t tsBytes[3];
    tsBytes[0] = (timestamp >> 16) & 0xFF;
    tsBytes[1] = (timestamp >> 8) & 0xFF;
    tsBytes[2] = timestamp & 0xFF;
    [chunkData appendBytes:tsBytes length:3];

    uint8_t lenBytes[3];
    lenBytes[0] = (length >> 16) & 0xFF;
    lenBytes[1] = (length >> 8) & 0xFF;
    lenBytes[2] = length & 0xFF;
    [chunkData appendBytes:lenBytes length:3];

    [chunkData appendBytes:&typeId length:1];

    // Stream ID (小端序)
    uint32_t sid = streamId;
    [chunkData appendBytes:&sid length:4];

    uint32_t sent = 0;
    uint32_t firstChunkSize = MIN(length, RTMP_OUT_CHUNK_SIZE);
    [chunkData appendBytes:bytes length:firstChunkSize];
    sent += firstChunkSize;

    [self sendRawData:chunkData];

    // 2. 后续 Chunks: Type 3 Header (1 字节)
    while (sent < length) {
        uint32_t chunkSize = MIN(length - sent, RTMP_OUT_CHUNK_SIZE);
        NSMutableData *subChunk = [NSMutableData dataWithCapacity:1 + chunkSize];

        uint8_t contHeader = (0x03 << 6) | (csid & 0x3F); // Type 3
        [subChunk appendBytes:&contHeader length:1];
        [subChunk appendBytes:bytes + sent length:chunkSize];
        sent += chunkSize;

        [self sendRawData:subChunk];
    }
}

#pragma mark - 底层 Socket & TLS I/O

- (BOOL)sendRawData:(NSData *)data {
    if (_socketFd < 0 || data.length == 0) return NO;
    return [self sendExactBytes:data.bytes length:data.length];
}

- (BOOL)sendExactBytes:(const void *)buffer length:(size_t)length {
    size_t totalSent = 0;
    const char *ptr = (const char *)buffer;

    while (totalSent < length) {
        if (_isTls && _sslContext) {
            size_t processed = 0;
            OSStatus status = SSLWrite(_sslContext, ptr + totalSent, length - totalSent, &processed);
            if (status != noErr && status != errSSLWouldBlock) {
                NSLog(@"[PdkRtmpClient] TLS 发送失败: %d", (int)status);
                [self handleNetworkDisconnect];
                return NO;
            }
            totalSent += processed;
            _bytesSentSinceLastCheck += (uint32_t)processed;
        } else {
            ssize_t sent = send(_socketFd, ptr + totalSent, length - totalSent, 0);
            if (sent <= 0) {
                NSLog(@"[PdkRtmpClient] Socket 发送失败: %s", strerror(errno));
                [self handleNetworkDisconnect];
                return NO;
            }
            totalSent += sent;
            _bytesSentSinceLastCheck += (uint32_t)sent;
        }
    }
    return YES;
}

- (BOOL)readExactBytes:(void *)buffer length:(size_t)length {
    size_t totalRead = 0;
    char *ptr = (char *)buffer;

    while (totalRead < length) {
        if (_isTls && _sslContext) {
            size_t processed = 0;
            OSStatus status = SSLRead(_sslContext, ptr + totalRead, length - totalRead, &processed);
            if (status != noErr && status != errSSLWouldBlock) {
                NSLog(@"[PdkRtmpClient] TLS 接收失败: %d", (int)status);
                return NO;
            }
            totalRead += processed;
        } else {
            ssize_t n = recv(_socketFd, ptr + totalRead, length - totalRead, 0);
            if (n <= 0) {
                NSLog(@"[PdkRtmpClient] Socket 接收失败: %s", strerror(errno));
                return NO;
            }
            totalRead += n;
        }
    }
    return YES;
}

- (ssize_t)readSomeBytes:(void *)buffer length:(size_t)maxLength {
    if (_isTls && _sslContext) {
        size_t processed = 0;
        OSStatus status = SSLRead(_sslContext, buffer, maxLength, &processed);
        if (status == noErr || status == errSSLWouldBlock) {
            return (ssize_t)processed;
        }
        return -1;
    } else {
        return recv(_socketFd, buffer, maxLength, 0);
    }
}

#pragma mark - 统计与状态

- (void)startBitrateTimer {
    [self stopBitrateTimer];

    _bitrateTimer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, _socketQueue);
    dispatch_source_set_timer(_bitrateTimer, dispatch_time(DISPATCH_TIME_NOW, 1 * NSEC_PER_SEC), 1 * NSEC_PER_SEC, 100 * NSEC_PER_MSEC);

    __weak typeof(self) weakSelf = self;
    dispatch_source_set_event_handler(_bitrateTimer, ^{
        __strong typeof(weakSelf) strongSelf = weakSelf;
        if (!strongSelf) return;

        uint32_t bytes = strongSelf->_bytesSentSinceLastCheck;
        strongSelf->_bytesSentSinceLastCheck = 0;
        strongSelf->_currentBitrateBps = bytes * 8;

        dispatch_async(dispatch_get_main_queue(), ^{
            [strongSelf.delegate rtmpClientDidUpdateBitrate:strongSelf->_currentBitrateBps];
        });
    });

    dispatch_resume(_bitrateTimer);
}

- (void)stopBitrateTimer {
    if (_bitrateTimer) {
        dispatch_source_cancel(_bitrateTimer);
        _bitrateTimer = nil;
    }
}

- (void)handleNetworkDisconnect {
    if (!_isConnected && !_isConnecting) return;
    [self disconnect];
    dispatch_async(dispatch_get_main_queue(), ^{
        [self.delegate rtmpClientDidDisconnect];
    });
}

- (void)notifyError:(NSString *)errMsg {
    NSLog(@"[PdkRtmpClient] 错误: %@", errMsg);
    [self disconnect];
    dispatch_async(dispatch_get_main_queue(), ^{
        [self.delegate rtmpClientDidFailWithError:errMsg];
    });
}

- (void)disconnect {
    _isConnected = NO;
    _isConnecting = NO;
    [self stopBitrateTimer];

    if (_sslContext) {
        SSLClose(_sslContext);
        CFRelease(_sslContext);
        _sslContext = NULL;
    }

    if (_socketFd >= 0) {
        close(_socketFd);
        _socketFd = -1;
    }
}

- (void)dealloc {
    [self disconnect];
}

@end
