import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  StyleSheet,
  View,
  Alert,
  StatusBar,
  Platform,
  PermissionsAndroid,
  Animated,
  AppState,
  AppStateStatus,
} from 'react-native';
import { Colors } from '../theme/colors';
import { Spacing } from '../theme/typography';
import { CameraViewfinder } from '../components/CameraViewfinder';
import { LiveOverlayHud } from '../components/LiveOverlayHud';
import { StreamControlBar } from '../components/StreamControlBar';
import { SettingsSheet, RESOLUTION_PRESETS } from '../components/SettingsSheet';
import { VideoAudioSettings, LoginResult, PdkEnv } from '../api/types';
import { liveService } from '../services/liveService';
import { rtmpEngine, StreamStats } from '../services/rtmpEngine';
import { pdkClient } from '../api/pdkClient';
import { devSettingsService } from '../services/devSettingsService';

interface LiveScreenProps {
  loginResult: LoginResult;
  onNavigateProfile: () => void;
}

/**
 * 直播主控室全景页面 (Live Broadcast Studio)
 * 整合全屏高清摄像头硬件预览、MediaCodec 编解码、RTMP 原生推流、自动隐藏控制台与开发者直推
 */
export const LiveScreen: React.FC<LiveScreenProps> = ({
  loginResult,
  onNavigateProfile,
}) => {
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [settingsSheetVisible, setSettingsSheetVisible] = useState(false);
  const [currentEnv, setCurrentEnv] = useState<PdkEnv>(pdkClient.getEnvironment());

  // 视频画面隐私开关 (替换原有补光灯，支持画面黑屏暂停推流)
  const [isVideoEnabled, setIsVideoEnabled] = useState(true);

  // 控制栏 10 秒无操作自动隐藏状态与动画
  const [controlsVisible, setControlsVisible] = useState(true);
  const hideTimerRef = useRef<NodeJS.Timeout | null>(null);
  const controlsOpacity = useRef(new Animated.Value(1)).current;

  // 高级专网模式：是否处于自定义直推 RTMP 模式
  const isDirectRtmpRef = useRef(false);

  // 音视频参数配置状态
  const [videoSettings, setVideoSettings] = useState<VideoAudioSettings>({
    resolution: RESOLUTION_PRESETS[0], // 默认 1080P
    bitrateKbps: 1800, // 默认 1800 kbps 流畅高清
    fps: 30, // 默认 30 FPS 标准稳定帧率
    audioBitrateKbps: 128,
    audioSampleRate: 48000,
    isMuted: false,
    isFrontCamera: true, // 默认前置主播自拍模式
    isTorchOn: false,
    beautyLevel: 3,
  });

  // 实时推流数据指标
  const [streamStats, setStreamStats] = useState<StreamStats>({
    fps: 0,
    bitrateKbps: 0,
    droppedFrames: 0,
    durationSeconds: 0,
    netQuality: 'DISCONNECTED',
  });

  // 重置并启动 10 秒自动隐藏倒计时
  const resetHideTimer = useCallback(() => {
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current);
    }
    setControlsVisible(true);
    Animated.timing(controlsOpacity, {
      toValue: 1,
      duration: 200,
      useNativeDriver: true,
    }).start();

    // 10秒无操作后自动平滑淡出隐藏
    hideTimerRef.current = setTimeout(() => {
      setControlsVisible(false);
      Animated.timing(controlsOpacity, {
        toValue: 0,
        duration: 300,
        useNativeDriver: true,
      }).start();
    }, 10000);
  }, [controlsOpacity]);

  // 设置抽屉打开时保持控制可见，关闭后重新开始 10s 倒计时
  useEffect(() => {
    if (settingsSheetVisible) {
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
      setControlsVisible(true);
      controlsOpacity.setValue(1);
    } else {
      resetHideTimer();
    }
  }, [settingsSheetVisible, resetHideTimer, controlsOpacity]);

  // 页面卸载时清理定时器
  useEffect(() => {
    return () => {
      if (hideTimerRef.current) {
        clearTimeout(hideTimerRef.current);
      }
    };
  }, []);

  // 点击屏幕视频画面：唤醒控制栏并检测摄像头健康，若出现异常黑屏立即静默自愈
  const handleScreenPress = useCallback(() => {
    resetHideTimer();
    if (!isStreaming) {
      rtmpEngine.checkCameraHealth().then((health) => {
        if (!health.isHealthy) {
          console.log('[LiveScreen] 点击触发摄像头静默自愈');
          rtmpEngine.recoverCamera().catch(() => {});
        }
      }).catch(() => {});
    }
  }, [resetHideTimer, isStreaming]);

  // 监听应用前后台切换生命周期，实现自动自愈与画面唤醒
  useEffect(() => {
    const handleAppStateChange = async (nextAppState: AppStateStatus) => {
      console.log(`[LiveScreen] AppState changed to: ${nextAppState}`);
      if (nextAppState === 'active') {
        // 从后台恢复至前台：执行相机健康自愈
        try {
          const health = await rtmpEngine.checkCameraHealth();
          if (!health.isHealthy || (!health.isOnPreview && !isStreaming)) {
            console.log('[LiveScreen] 回前台检测到取景未激活，自动恢复硬件摄像头画面');
            await rtmpEngine.startPreview(
              videoSettings.isFrontCamera,
              videoSettings.resolution.width,
              videoSettings.resolution.height,
              videoSettings.fps
            );
          }
        } catch (e) {
          console.warn('[LiveScreen] 回前台恢复取景异常:', e);
        }
      }
    };

    const subscription = AppState.addEventListener('change', handleAppStateChange);
    return () => {
      subscription.remove();
    };
  }, [isStreaming, videoSettings]);

  // 请求系统摄像头与音频权限，并在授权后自动开启底层硬件取景预览
  useEffect(() => {
    async function initCameraPreview() {
      if (Platform.OS === 'android') {
        try {
          const permissions = [
            PermissionsAndroid.PERMISSIONS.CAMERA,
            PermissionsAndroid.PERMISSIONS.RECORD_AUDIO,
          ];
          const results = await PermissionsAndroid.requestMultiple(permissions);
          const hasCamera = results[PermissionsAndroid.PERMISSIONS.CAMERA] === PermissionsAndroid.RESULTS.GRANTED;
          const hasAudio = results[PermissionsAndroid.PERMISSIONS.RECORD_AUDIO] === PermissionsAndroid.RESULTS.GRANTED;

          if (hasCamera && hasAudio) {
            await rtmpEngine.startPreview(
              videoSettings.isFrontCamera,
              videoSettings.resolution.width,
              videoSettings.resolution.height,
              videoSettings.fps
            );
          } else if (!hasCamera) {
            Alert.alert('权限受限', '未授予摄像头权限，无法使用硬件镜头取景');
          }
        } catch (e) {
          console.warn('[LiveScreen] 请求权限或启动预览异常:', e);
        }
      }
    }

    initCameraPreview();

    return () => {
      if (isStreaming) {
        rtmpEngine.stopPublish().catch(() => {});
      }
      rtmpEngine.stopPreview();
    };
  }, []);

  // 监听推流引擎实时采样数据与网络状态
  useEffect(() => {
    const unsubStats = rtmpEngine.subscribeStats((stats) => {
      setStreamStats(stats);
    });

    const unsubState = rtmpEngine.subscribeState((state, error) => {
      if (state === 'CONNECTED') {
        setIsStreaming(true);
      } else if (state === 'DISCONNECTED') {
        setIsStreaming(false);
      } else if (state === 'FAILED') {
        setIsStreaming(false);
        Alert.alert('推流失败', error || '流媒体服务器连接失败，请检查 RTMP 地址或网络');
      }
    });

    const unsubLive = liveService.addListener({
      onStateChange: (live) => {
        setIsStreaming(live);
      },
      onError: (errMsg) => {
        Alert.alert('推流提示', errMsg);
      },
    });

    return () => {
      unsubStats();
      unsubState();
      unsubLive();
    };
  }, []);

  // 1. 镜头前后翻转 (前摄 <-> 后摄)
  const handleFlipCamera = useCallback(async () => {
    await rtmpEngine.switchCamera();
    setVideoSettings((prev) => ({
      ...prev,
      isFrontCamera: !prev.isFrontCamera,
    }));
  }, []);

  // 2. 麦克风静音切换
  const handleToggleMute = useCallback(async () => {
    const nextMuted = !videoSettings.isMuted;
    await rtmpEngine.setMute(nextMuted);
    setVideoSettings((prev) => ({
      ...prev,
      isMuted: nextMuted,
    }));
  }, [videoSettings.isMuted]);

  // 3. 画面暂停 / 恢复开关 (隐私黑屏遮蔽，麦克风继续传输)
  const handleToggleVideo = useCallback(() => {
    setIsVideoEnabled((prev) => !prev);
  }, []);

  // 4. 开始 / 结束推流主动作 (支持开发者自定义 RTMP 直推旁路)
  const handleToggleStream = async () => {
    resetHideTimer();
    if (isStreaming) {
      Alert.alert('结束直播', '确定要停止当前直播推流吗？', [
        { text: '取消', style: 'cancel' },
        {
          text: '确定结束',
          style: 'destructive',
          onPress: async () => {
            setIsLoading(true);
            try {
              await rtmpEngine.stopPublish();
              if (!isDirectRtmpRef.current) {
                try {
                  await liveService.stopLive();
                } catch (e) {
                  console.warn('[LiveScreen] stopLive error:', e);
                }
              } else {
                setIsStreaming(false);
              }
            } finally {
              setIsLoading(false);
              isDirectRtmpRef.current = false;
            }
          },
        },
      ]);
    } else {
      setIsLoading(true);
      try {
        const isDirect = devSettingsService.isDirectRtmp();
        const customRtmp = devSettingsService.getCustomRtmpUrl();

        if (isDirect && customRtmp) {
          // 专网直推模式：直接推流到用户指定的 RTMP 服务器，无需请求业务后端
          console.log('[LiveScreen] 专网直推模式已启用自定义 RTMP 地址:', customRtmp);
          isDirectRtmpRef.current = true;
          await rtmpEngine.startPublish(customRtmp, videoSettings);
          setIsStreaming(true);
        } else {
          // 生产/标准模式：向业务后端请求推流票据与 RTMP 上行地址
          isDirectRtmpRef.current = false;
          const ticket = await liveService.startLive('智播移动端开播');
          await rtmpEngine.startPublish(ticket.publishUrl, videoSettings);
        }
      } catch (err: any) {
        isDirectRtmpRef.current = false;
        Alert.alert('开播失败', err?.message || '无法建立推流通道，请检查网络或 RTMP 地址');
      } finally {
        setIsLoading(false);
      }
    }
  };

  const handleUpdateSettings = useCallback(
    async (newPartial: Partial<VideoAudioSettings>) => {
      setVideoSettings((prev) => ({ ...prev, ...newPartial }));

      // 若正在推流中，用户调整码率，立即动态下发底层 MediaCodec 硬件编码器 (On-the-fly)
      if (isStreaming && newPartial.bitrateKbps) {
        try {
          await rtmpEngine.setBitrate(newPartial.bitrateKbps);
          console.log(`[LiveScreen] 动态调码率成功: ${newPartial.bitrateKbps} kbps`);
        } catch (e) {
          console.warn('[LiveScreen] 动态调码率异常:', e);
        }
      }
    },
    [isStreaming]
  );

  const handleUpdateEnv = (newEnv: PdkEnv) => {
    setCurrentEnv(newEnv);
    pdkClient.setEnvironment(newEnv);
  };

  const maskedPhone = loginResult.phone
    ? `${loginResult.phone.slice(0, 3)}****${loginResult.phone.slice(-4)}`
    : '主播';

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" translucent backgroundColor="transparent" />

      {/* 1. 全景高清摄像头取景框 (支持轻触屏幕唤醒控制栏、画面黑屏遮蔽) */}
      <CameraViewfinder
        isFrontCamera={videoSettings.isFrontCamera}
        isMuted={videoSettings.isMuted}
        isVideoEnabled={isVideoEnabled}
        resolutionLabel={videoSettings.resolution.label}
        onScreenPress={handleScreenPress}
      />

      {/* 2. 顶部悬浮流状态看板 HUD */}
      <LiveOverlayHud
        isStreaming={isStreaming}
        stats={streamStats}
        resolutionLabel={videoSettings.resolution.label}
        maskedPhone={maskedPhone}
        onProfilePress={() => {
          resetHideTimer();
          if (isStreaming) {
            Alert.alert(
              '直播进行中',
              '当前正在实时推流，离开直播间将结束本次直播。是否确定前往管理中心？',
              [
                { text: '取消', style: 'cancel' },
                {
                  text: '结束并前往',
                  style: 'destructive',
                  onPress: async () => {
                    await rtmpEngine.stopPublish().catch(() => {});
                    try {
                      await liveService.stopLive().catch(() => {});
                    } catch {}
                    setIsStreaming(false);
                    onNavigateProfile();
                  },
                },
              ]
            );
          } else {
            onNavigateProfile();
          }
        }}
      />

      {/* 3. 底部悬浮控制台 (支持 10 秒无操作自动平滑淡出隐藏) */}
      <Animated.View
        style={[styles.controlBarWrapper, { opacity: controlsOpacity }]}
        pointerEvents={controlsVisible ? 'auto' : 'none'}
      >
        <StreamControlBar
          isStreaming={isStreaming}
          isLoading={isLoading}
          isFrontCamera={videoSettings.isFrontCamera}
          isMuted={videoSettings.isMuted}
          isVideoEnabled={isVideoEnabled}
          onFlipCamera={handleFlipCamera}
          onToggleMute={handleToggleMute}
          onToggleVideo={handleToggleVideo}
          onOpenSettings={() => {
            resetHideTimer();
            setSettingsSheetVisible(true);
          }}
          onToggleStream={handleToggleStream}
          onUserInteraction={resetHideTimer}
        />
      </Animated.View>

      {/* 4. 底部毛玻璃画质设置抽屉 */}
      <SettingsSheet
        visible={settingsSheetVisible}
        settings={videoSettings}
        currentEnv={currentEnv}
        onUpdateSettings={handleUpdateSettings}
        onUpdateEnv={handleUpdateEnv}
        onClose={() => setSettingsSheetVisible(false)}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.background,
  },
  controlBarWrapper: {
    position: 'absolute',
    bottom: 36,
    left: Spacing.md,
    right: Spacing.md,
    zIndex: 20,
  },
});
