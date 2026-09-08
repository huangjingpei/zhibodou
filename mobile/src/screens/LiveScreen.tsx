import React, { useState, useEffect, useCallback } from 'react';
import { StyleSheet, View, Alert, StatusBar, Platform, PermissionsAndroid } from 'react-native';
import { Colors } from '../theme/colors';
import { CameraViewfinder } from '../components/CameraViewfinder';
import { LiveOverlayHud } from '../components/LiveOverlayHud';
import { StreamControlBar } from '../components/StreamControlBar';
import { SettingsSheet, RESOLUTION_PRESETS } from '../components/SettingsSheet';
import { VideoAudioSettings, LoginResult, PdkEnv } from '../api/types';
import { liveService } from '../services/liveService';
import { rtmpEngine, StreamStats } from '../services/rtmpEngine';
import { pdkClient } from '../api/pdkClient';

interface LiveScreenProps {
  loginResult: LoginResult;
  onNavigateProfile: () => void;
}

/**
 * 直播主控室全景页面 (Live Broadcast Studio)
 * 整合全屏高清摄像头硬件预览、MediaCodec 编解码、RTMP 原生推流与顶部流状态 HUD
 */
export const LiveScreen: React.FC<LiveScreenProps> = ({
  loginResult,
  onNavigateProfile,
}) => {
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [settingsSheetVisible, setSettingsSheetVisible] = useState(false);
  const [currentEnv, setCurrentEnv] = useState<PdkEnv>(pdkClient.getEnvironment());

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
      rtmpEngine.stopPreview();
    };
  }, []);

  // 监听推流引擎实时采样数据与网络状态
  useEffect(() => {
    const unsubStats = rtmpEngine.subscribeStats((stats) => {
      setStreamStats(stats);
    });

    const unsubState = rtmpEngine.subscribeState((state, error) => {
      if (state === 'FAILED') {
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
      isTorchOn: false,
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

  // 3. 闪光补光灯开关 (仅后摄支持)
  const handleToggleTorch = useCallback(async () => {
    const nextTorch = !videoSettings.isTorchOn;
    await rtmpEngine.toggleTorch(nextTorch);
    setVideoSettings((prev) => ({
      ...prev,
      isTorchOn: nextTorch,
    }));
  }, [videoSettings.isTorchOn]);

  // 4. 开始 / 结束推流主动作
  const handleToggleStream = async () => {
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
              await liveService.stopLive();
            } finally {
              setIsLoading(false);
            }
          },
        },
      ]);
    } else {
      setIsLoading(true);
      try {
        const ticket = await liveService.startLive('智播移动端开播');
        await rtmpEngine.startPublish(ticket.publishUrl, videoSettings);
      } catch (err: any) {
        Alert.alert('开播失败', err?.message || '无法建立推流通道，请重试');
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

      {/* 1. 全景高清摄像头取景框 */}
      <CameraViewfinder
        isFrontCamera={videoSettings.isFrontCamera}
        isMuted={videoSettings.isMuted}
        isTorchOn={videoSettings.isTorchOn}
        resolutionLabel={videoSettings.resolution.label}
      />

      {/* 2. 顶部悬浮流状态看板 HUD */}
      <LiveOverlayHud
        isStreaming={isStreaming}
        stats={streamStats}
        resolutionLabel={videoSettings.resolution.label}
        maskedPhone={maskedPhone}
        onProfilePress={onNavigateProfile}
      />

      {/* 3. 底部悬浮控制台 (翻转、静音、补光、参数、主开关) */}
      <StreamControlBar
        isStreaming={isStreaming}
        isLoading={isLoading}
        isFrontCamera={videoSettings.isFrontCamera}
        isMuted={videoSettings.isMuted}
        isTorchOn={videoSettings.isTorchOn}
        onFlipCamera={handleFlipCamera}
        onToggleMute={handleToggleMute}
        onToggleTorch={handleToggleTorch}
        onOpenSettings={() => setSettingsSheetVisible(true)}
        onToggleStream={handleToggleStream}
      />

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
});
