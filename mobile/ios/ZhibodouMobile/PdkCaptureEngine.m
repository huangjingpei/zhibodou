//
//  PdkCaptureEngine.m
//  ZhibodouMobile
//
//  Created for Zhibodou Live SDK.
//

#import "PdkCaptureEngine.h"

@interface PdkCaptureEngine () <AVCaptureVideoDataOutputSampleBufferDelegate, AVCaptureAudioDataOutputSampleBufferDelegate> {
    dispatch_queue_t _captureSessionQueue;
    dispatch_queue_t _videoOutputQueue;
    dispatch_queue_t _audioOutputQueue;

    AVCaptureDeviceInput *_videoInput;
    AVCaptureDeviceInput *_audioInput;
    AVCaptureVideoDataOutput *_videoOutput;
    AVCaptureAudioDataOutput *_audioOutput;

    int _targetFps;
    BOOL _shouldBeRunning;
    BOOL _isInterrupted;
}
@end

@implementation PdkCaptureEngine

- (instancetype)init {
    self = [super init];
    if (self) {
        _captureSession = [[AVCaptureSession alloc] init];
        _captureSessionQueue = dispatch_queue_create("com.zhibodou.mobile.sessionQueue", DISPATCH_QUEUE_SERIAL);
        _videoOutputQueue = dispatch_queue_create("com.zhibodou.mobile.videoCaptureQueue", DISPATCH_QUEUE_SERIAL);
        _audioOutputQueue = dispatch_queue_create("com.zhibodou.mobile.audioCaptureQueue", DISPATCH_QUEUE_SERIAL);

        _isFrontCamera = YES;
        _isMuted = NO;
        _isTorchOn = NO;
        _targetFps = 30;
        _shouldBeRunning = NO;
        _isInterrupted = NO;

        [self registerSessionNotifications];
    }
    return self;
}

- (void)registerSessionNotifications {
    NSNotificationCenter *nc = [NSNotificationCenter defaultCenter];
    [nc addObserver:self
           selector:@selector(sessionWasInterrupted:)
               name:AVCaptureSessionWasInterruptedNotification
             object:_captureSession];
    [nc addObserver:self
           selector:@selector(sessionInterruptionEnded:)
               name:AVCaptureSessionInterruptionEndedNotification
             object:_captureSession];
    [nc addObserver:self
           selector:@selector(sessionRuntimeError:)
               name:AVCaptureSessionRuntimeErrorNotification
             object:_captureSession];
}

- (void)sessionWasInterrupted:(NSNotification *)notification {
    _isInterrupted = YES;
    NSInteger reason = [notification.userInfo[AVCaptureSessionInterruptionReasonKey] integerValue];
    NSLog(@"[PdkCaptureEngine] AVCaptureSession 被系统打断 (Reason=%ld)", (long)reason);
}

- (void)sessionInterruptionEnded:(NSNotification *)notification {
    NSLog(@"[PdkCaptureEngine] AVCaptureSession 系统打断结束，正在尝试自愈恢复...");
    _isInterrupted = NO;
    if (_shouldBeRunning) {
        dispatch_async(_captureSessionQueue, ^{
            if (!self->_captureSession.isRunning) {
                [self->_captureSession startRunning];
                NSLog(@"[PdkCaptureEngine] 打断恢复完成，AVCaptureSession 已重新启动");
            }
        });
    }
}

- (void)sessionRuntimeError:(NSNotification *)notification {
    NSError *error = notification.userInfo[AVCaptureSessionErrorKey];
    NSLog(@"[PdkCaptureEngine] AVCaptureSession 运行时错误: %@", error);

    // 如果系统 media services 发生重置或设备故障，自动尝试全链路自愈恢复
    if (error.code == AVErrorMediaServicesWereReset || self->_shouldBeRunning) {
        dispatch_async(self->_captureSessionQueue, ^{
            [self recoverSessionInternal];
        });
    }
}

- (BOOL)isRunning {
    return _captureSession.isRunning;
}

- (BOOL)isInterrupted {
    return _isInterrupted;
}

- (AVCaptureDevice *)cameraWithPosition:(AVCaptureDevicePosition)position {
    AVCaptureDeviceDiscoverySession *discovery = [AVCaptureDeviceDiscoverySession
        discoverySessionWithDeviceTypes:@[AVCaptureDeviceTypeBuiltInWideAngleCamera]
                              mediaType:AVMediaTypeVideo
                               position:position];
    return discovery.devices.firstObject;
}

- (BOOL)startPreviewWithFront:(BOOL)isFront fps:(int)fps {
    _isFrontCamera = isFront;
    _targetFps = fps > 0 ? fps : 30;
    _shouldBeRunning = YES;

    dispatch_async(_captureSessionQueue, ^{
        [self setupAudioSession];
        [self setupCaptureSession];
        if (!self->_captureSession.isRunning) {
            [self->_captureSession startRunning];
            NSLog(@"[PdkCaptureEngine] 摄像头采集已启动 (前摄: %d, %d fps)", self->_isFrontCamera, self->_targetFps);
        }
    });

    return YES;
}

- (void)stopPreview {
    _shouldBeRunning = NO;
    dispatch_async(_captureSessionQueue, ^{
        if (self->_captureSession.isRunning) {
            [self->_captureSession stopRunning];
            NSLog(@"[PdkCaptureEngine] 摄像头采集已停止");
        }
    });
}

- (BOOL)recoverSessionInternal {
    NSLog(@"[PdkCaptureEngine] 执行底层硬件采集管线自愈重置...");
    if (_captureSession.isRunning) {
        [_captureSession stopRunning];
    }
    [self setupAudioSession];
    [self setupCaptureSession];
    if (!_captureSession.isRunning) {
        [_captureSession startRunning];
    }
    _isInterrupted = NO;
    NSLog(@"[PdkCaptureEngine] 底层硬件采集管线自愈完成，状态: isRunning=%d", _captureSession.isRunning);
    return _captureSession.isRunning;
}

- (BOOL)recoverSession {
    _shouldBeRunning = YES;
    __block BOOL success = NO;
    dispatch_sync(_captureSessionQueue, ^{
        success = [self recoverSessionInternal];
    });
    return success;
}

- (void)setupAudioSession {
    AVAudioSession *audioSession = [AVAudioSession sharedInstance];
    NSError *error = nil;
    [audioSession setCategory:AVAudioSessionCategoryPlayAndRecord
                  withOptions:AVAudioSessionCategoryOptionDefaultToSpeaker | AVAudioSessionCategoryOptionAllowBluetooth
                        error:&error];
    if (error) {
        NSLog(@"[PdkCaptureEngine] AVAudioSession 配置警告: %@", error);
    }
    [audioSession setActive:YES error:nil];
}

- (void)setupCaptureSession {
    [_captureSession beginConfiguration];

    // 1. 设置会话清晰度 (优先 1080P，若硬件不支持回退 720P)
    if ([_captureSession canSetSessionPreset:AVCaptureSessionPreset1920x1080]) {
        _captureSession.sessionPreset = AVCaptureSessionPreset1920x1080;
    } else if ([_captureSession canSetSessionPreset:AVCaptureSessionPreset1280x720]) {
        _captureSession.sessionPreset = AVCaptureSessionPreset1280x720;
    } else {
        _captureSession.sessionPreset = AVCaptureSessionPresetHigh;
    }

    // 2. 配置视频输入
    AVCaptureDevicePosition position = _isFrontCamera ? AVCaptureDevicePositionFront : AVCaptureDevicePositionBack;
    AVCaptureDevice *videoDevice = [self cameraWithPosition:position];
    if (videoDevice) {
        // 设置帧率
        NSError *lockErr = nil;
        if ([videoDevice lockForConfiguration:&lockErr]) {
            videoDevice.activeVideoMinFrameDuration = CMTimeMake(1, _targetFps);
            videoDevice.activeVideoMaxFrameDuration = CMTimeMake(1, _targetFps);
            [videoDevice unlockForConfiguration];
        }

        NSError *inErr = nil;
        if (_videoInput) {
            [_captureSession removeInput:_videoInput];
        }
        _videoInput = [AVCaptureDeviceInput deviceInputWithDevice:videoDevice error:&inErr];
        if ([_captureSession canAddInput:_videoInput]) {
            [_captureSession addInput:_videoInput];
        }
    }

    // 3. 配置音频输入
    if (!_audioInput) {
        AVCaptureDevice *audioDevice = [AVCaptureDevice defaultDeviceWithMediaType:AVMediaTypeAudio];
        if (audioDevice) {
            _audioInput = [AVCaptureDeviceInput deviceInputWithDevice:audioDevice error:nil];
            if ([_captureSession canAddInput:_audioInput]) {
                [_captureSession addInput:_audioInput];
            }
        }
    }

    // 4. 配置视频输出
    if (!_videoOutput) {
        _videoOutput = [[AVCaptureVideoDataOutput alloc] init];
        _videoOutput.alwaysDiscardsLateVideoFrames = YES;
        _videoOutput.videoSettings = @{
            (id)kCVPixelBufferPixelFormatTypeKey: @(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange)
        };
        [_videoOutput setSampleBufferDelegate:self queue:_videoOutputQueue];
        if ([_captureSession canAddOutput:_videoOutput]) {
            [_captureSession addOutput:_videoOutput];
        }
    }

    // 5. 配置音频输出
    if (!_audioOutput) {
        _audioOutput = [[AVCaptureAudioDataOutput alloc] init];
        [_audioOutput setSampleBufferDelegate:self queue:_audioOutputQueue];
        if ([_captureSession canAddOutput:_audioOutput]) {
            [_captureSession addOutput:_audioOutput];
        }
    }

    // 6. 配置视频连线方向与镜像
    AVCaptureConnection *videoConnection = [_videoOutput connectionWithMediaType:AVMediaTypeVideo];
    if (videoConnection.isVideoOrientationSupported) {
        videoConnection.videoOrientation = AVCaptureVideoOrientationPortrait;
    }
    if (videoConnection.isVideoMirroringSupported) {
        videoConnection.videoMirrored = _isFrontCamera;
    }

    [_captureSession commitConfiguration];
}

- (BOOL)switchCamera {
    __block BOOL success = NO;
    dispatch_sync(_captureSessionQueue, ^{
        self->_isFrontCamera = !self->_isFrontCamera;
        self->_isTorchOn = NO; // 翻转后重置闪光灯

        [self->_captureSession beginConfiguration];

        if (self->_videoInput) {
            [self->_captureSession removeInput:self->_videoInput];
        }

        AVCaptureDevicePosition position = self->_isFrontCamera ? AVCaptureDevicePositionFront : AVCaptureDevicePositionBack;
        AVCaptureDevice *newDevice = [self cameraWithPosition:position];
        if (newDevice) {
            NSError *lockErr = nil;
            if ([newDevice lockForConfiguration:&lockErr]) {
                newDevice.activeVideoMinFrameDuration = CMTimeMake(1, self->_targetFps);
                newDevice.activeVideoMaxFrameDuration = CMTimeMake(1, self->_targetFps);
                [newDevice unlockForConfiguration];
            }

            self->_videoInput = [AVCaptureDeviceInput deviceInputWithDevice:newDevice error:nil];
            if ([self->_captureSession canAddInput:self->_videoInput]) {
                [self->_captureSession addInput:self->_videoInput];
                success = YES;
            }
        }

        AVCaptureConnection *videoConnection = [self->_videoOutput connectionWithMediaType:AVMediaTypeVideo];
        if (videoConnection.isVideoOrientationSupported) {
            videoConnection.videoOrientation = AVCaptureVideoOrientationPortrait;
        }
        if (videoConnection.isVideoMirroringSupported) {
            videoConnection.videoMirrored = self->_isFrontCamera;
        }

        [self->_captureSession commitConfiguration];
        NSLog(@"[PdkCaptureEngine] 翻转镜头成功 (当前前置: %d)", self->_isFrontCamera);
    });

    return success;
}

- (BOOL)toggleTorch:(BOOL)enable {
    if (_isFrontCamera) {
        NSLog(@"[PdkCaptureEngine] 前置摄像头不支持补光灯");
        return NO;
    }

    AVCaptureDevice *device = _videoInput.device;
    if (!device || ![device hasTorch]) {
        return NO;
    }

    NSError *error = nil;
    if ([device lockForConfiguration:&error]) {
        if (enable && [device isTorchModeSupported:AVCaptureTorchModeOn]) {
            [device setTorchMode:AVCaptureTorchModeOn];
            _isTorchOn = YES;
        } else if (!enable && [device isTorchModeSupported:AVCaptureTorchModeOff]) {
            [device setTorchMode:AVCaptureTorchModeOff];
            _isTorchOn = NO;
        }
        [device unlockForConfiguration];
        NSLog(@"[PdkCaptureEngine] 补光灯已设为: %d", _isTorchOn);
        return YES;
    }
    return NO;
}

- (BOOL)setMuted:(BOOL)muted {
    _isMuted = muted;
    NSLog(@"[PdkCaptureEngine] 麦克风静音状态: %d", _isMuted);
    return YES;
}

#pragma mark - AVCapture Delegates

- (void)captureOutput:(AVCaptureOutput *)output
didOutputSampleBuffer:(CMSampleBufferRef)sampleBuffer
       fromConnection:(AVCaptureConnection *)connection {
    if (output == _videoOutput) {
        [self.delegate captureEngineDidOutputVideoSampleBuffer:sampleBuffer];
    } else if (output == _audioOutput) {
        if (!_isMuted) {
            [self.delegate captureEngineDidOutputAudioSampleBuffer:sampleBuffer];
        }
    }
}

- (void)dealloc {
    [[NSNotificationCenter defaultCenter] removeObserver:self];
    [self stopPreview];
}

@end
