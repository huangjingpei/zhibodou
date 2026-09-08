import React, { useState } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableWithoutFeedback,
  GestureResponderEvent,
  Animated,
  useWindowDimensions,
} from 'react-native';
import { Colors } from '../theme/colors';
import { Typography } from '../theme/typography';

import { PdkCameraNativeView } from './PdkCameraNativeView';

interface CameraViewfinderProps {
  isFrontCamera: boolean;
  isMuted: boolean;
  isTorchOn: boolean;
  resolutionLabel: string;
}

/**
 * 现代全屏摄像头取景框组件
 * 深度集成 Android 原生硬件摄像头画面 (PdkCameraNativeView)、构图辅助九宫格线、轻触测光对焦光圈
 * 具备 9:16 标准视频画幅等比居中裁剪算法，消灭畸变与上下黑边
 */
export const CameraViewfinder: React.FC<CameraViewfinderProps> = ({
  isFrontCamera,
  isMuted,
  isTorchOn,
  resolutionLabel,
}) => {
  const { width: screenWidth, height: screenHeight } = useWindowDimensions();
  const [focusPos, setFocusPos] = useState<{ x: number; y: number } | null>(null);
  const [focusAnim] = useState(new Animated.Value(0));

  // 9:16 标准推流画幅等比居中裁剪计算
  const TARGET_ASPECT = 9 / 16;
  const screenAspect = screenHeight > 0 ? screenWidth / screenHeight : TARGET_ASPECT;

  let cameraWidth = screenWidth;
  let cameraHeight = screenHeight;
  let cameraLeft = 0;
  let cameraTop = 0;

  if (screenAspect < TARGET_ASPECT) {
    // 手机屏幕比 9:16 更窄更长（现代全面屏）
    cameraHeight = screenHeight;
    cameraWidth = Math.round(screenHeight * TARGET_ASPECT);
    cameraLeft = Math.round((screenWidth - cameraWidth) / 2);
  } else {
    // 屏幕比 9:16 更宽（如平板或横屏）
    cameraWidth = screenWidth;
    cameraHeight = Math.round(screenWidth / TARGET_ASPECT);
    cameraTop = Math.round((screenHeight - cameraHeight) / 2);
  }

  const handleTapToFocus = (e: GestureResponderEvent) => {
    const { locationX, locationY } = e.nativeEvent;
    setFocusPos({ x: locationX, y: locationY });
    focusAnim.setValue(0);

    Animated.sequence([
      Animated.timing(focusAnim, {
        toValue: 1,
        duration: 300,
        useNativeDriver: true,
      }),
      Animated.delay(1000),
      Animated.timing(focusAnim, {
        toValue: 0,
        duration: 250,
        useNativeDriver: true,
      }),
    ]).start(() => {
      setFocusPos(null);
    });
  };

  return (
    <TouchableWithoutFeedback onPress={handleTapToFocus}>
      <View style={styles.container}>
        {/* 1. Android 原生硬件摄像头真实取景画面 (由底层 OpenGlView 精确执行 9:16 等比居中 Viewport 渲染) */}
        <View style={styles.cameraCropContainer}>
          <PdkCameraNativeView style={StyleSheet.absoluteFillObject} />
        </View>

        {/* 2. 状态标签与镜头指示 HUD */}
        <View style={styles.overlayInfo} pointerEvents="none">
          <Text style={styles.cameraWatermark}>
            {isFrontCamera ? '📱 前置高清自拍 (镜像模式)' : '📷 后置高清主摄'} · {resolutionLabel}
          </Text>

          {isTorchOn && !isFrontCamera && (
            <View style={styles.torchIndicator}>
              <Text style={styles.torchText}>⚡ 补光灯已开启</Text>
            </View>
          )}

          {isMuted && (
            <View style={styles.mutedPill}>
              <Text style={styles.mutedText}>🔇 麦克风已静音</Text>
            </View>
          )}
        </View>

        {/* 构图九宫格网格线 (Rule of Thirds) */}
        <View style={styles.gridOverlay} pointerEvents="none">
          <View style={[styles.gridLineH, { top: '33.33%' }]} />
          <View style={[styles.gridLineH, { top: '66.66%' }]} />
          <View style={[styles.gridLineV, { left: '33.33%' }]} />
          <View style={[styles.gridLineV, { left: '66.66%' }]} />
        </View>

        {/* 点击测光对焦方框动画 */}
        {focusPos && (
          <Animated.View
            pointerEvents="none"
            style={[
              styles.focusBox,
              {
                left: focusPos.x - 30,
                top: focusPos.y - 30,
                opacity: focusAnim,
                transform: [
                  {
                    scale: focusAnim.interpolate({
                      inputRange: [0, 1],
                      outputRange: [1.4, 1.0],
                    }),
                  },
                ],
              },
            ]}
          >
            <View style={styles.focusCenterDot} />
          </Animated.View>
        )}
      </View>
    </TouchableWithoutFeedback>
  );
};

const styles = StyleSheet.create({
  container: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: '#05070D',
  },
  cameraCropContainer: {
    ...StyleSheet.absoluteFillObject,
    overflow: 'hidden',
  },
  overlayInfo: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    paddingTop: 108,
  },
  simulatedCamera: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#0d131f',
  },
  frontMirror: {
    transform: [{ scaleX: -1 }],
  },
  lensGridCrosshair: {
    width: 44,
    height: 44,
    justifyContent: 'center',
    alignItems: 'center',
    opacity: 0.25,
  },
  crosshairH: {
    position: 'absolute',
    width: 24,
    height: 1,
    backgroundColor: Colors.textPrimary,
  },
  crosshairV: {
    position: 'absolute',
    width: 1,
    height: 24,
    backgroundColor: Colors.textPrimary,
  },
  cameraWatermark: {
    ...Typography.bodySmall,
    color: 'rgba(255, 255, 255, 0.35)',
    marginTop: 16,
    letterSpacing: 0.8,
  },
  torchIndicator: {
    position: 'absolute',
    top: 100,
    backgroundColor: 'rgba(245, 158, 11, 0.25)',
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: 'rgba(245, 158, 11, 0.5)',
  },
  torchText: {
    ...Typography.badge,
    color: Colors.warningYellow,
  },
  mutedPill: {
    position: 'absolute',
    bottom: 140,
    backgroundColor: 'rgba(239, 68, 68, 0.25)',
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: 'rgba(239, 68, 68, 0.5)',
  },
  mutedText: {
    ...Typography.badge,
    color: Colors.liveRed,
  },
  gridOverlay: {
    ...StyleSheet.absoluteFillObject,
  },
  gridLineH: {
    position: 'absolute',
    left: 0,
    right: 0,
    height: 0.5,
    backgroundColor: 'rgba(255, 255, 255, 0.08)',
  },
  gridLineV: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    width: 0.5,
    backgroundColor: 'rgba(255, 255, 255, 0.08)',
  },
  focusBox: {
    position: 'absolute',
    width: 60,
    height: 60,
    borderWidth: 1.5,
    borderColor: Colors.primary,
    borderRadius: 8,
    justifyContent: 'center',
    alignItems: 'center',
  },
  focusCenterDot: {
    width: 4,
    height: 4,
    borderRadius: 2,
    backgroundColor: Colors.primary,
  },
});
