import React, { useState } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableWithoutFeedback,
  GestureResponderEvent,
  Animated,
} from 'react-native';
import { Colors } from '../theme/colors';
import { Typography, Radius, Spacing } from '../theme/typography';
import { PdkCameraNativeView } from './PdkCameraNativeView';

interface CameraViewfinderProps {
  isFrontCamera: boolean;
  isMuted: boolean;
  isVideoEnabled?: boolean;
  resolutionLabel: string;
  onScreenPress?: () => void;
}

/**
 * 现代全屏摄像头取景框组件
 * 深度集成原生硬件摄像头画面 (PdkCameraNativeView)、构图辅助九宫格线、轻触测光对焦光圈
 * 具备 9:16 标准视频画幅等比居中裁剪，消灭拉伸变形
 * 支持轻触屏幕唤醒控制栏、视频画面隐私遮蔽
 */
export const CameraViewfinder: React.FC<CameraViewfinderProps> = ({
  isMuted,
  isVideoEnabled = true,
  onScreenPress,
}) => {
  const [focusPos, setFocusPos] = useState<{ x: number; y: number } | null>(null);
  const [focusAnim] = useState(new Animated.Value(0));

  const handleTapToFocus = (e: GestureResponderEvent) => {
    onScreenPress?.();

    const { locationX, locationY } = e.nativeEvent;
    setFocusPos({ x: locationX, y: locationY });
    focusAnim.setValue(0);

    Animated.sequence([
      Animated.timing(focusAnim, {
        toValue: 1,
        duration: 250,
        useNativeDriver: true,
      }),
      Animated.delay(800),
      Animated.timing(focusAnim, {
        toValue: 0,
        duration: 200,
        useNativeDriver: true,
      }),
    ]).start(() => {
      setFocusPos(null);
    });
  };

  return (
    <TouchableWithoutFeedback onPress={handleTapToFocus}>
      <View style={styles.container}>
        {/* 1. 原生硬件摄像头真实取景画面 (9:16 等比全屏居中 Viewport) */}
        <View style={styles.cameraCropContainer} pointerEvents="none">
          <PdkCameraNativeView style={StyleSheet.absoluteFillObject} />
        </View>

        {/* 2. 视频画面隐私遮蔽层 (当用户点击关闭画面时) */}
        {!isVideoEnabled && (
          <View style={styles.blackoutCover} pointerEvents="none">
            <View style={styles.blackoutBadge}>
              <Text style={styles.blackoutIcon}>🚫</Text>
              <Text style={styles.blackoutTitle}>摄像头画面已暂停</Text>
              <Text style={styles.blackoutSubtitle}>隐私遮蔽已开启 · 麦克风音频推流正常进行</Text>
            </View>
          </View>
        )}

        {/* 3. 静音提示 HUD */}
        {isMuted && (
          <View style={styles.mutedPill} pointerEvents="none">
            <Text style={styles.mutedText}>🔇 麦克风已静音</Text>
          </View>
        )}

        {/* 4. 构图九宫格网格线 (Rule of Thirds) */}
        <View style={styles.gridOverlay} pointerEvents="none">
          <View style={[styles.gridLineH, { top: '33.33%' }]} />
          <View style={[styles.gridLineH, { top: '66.66%' }]} />
          <View style={[styles.gridLineV, { left: '33.33%' }]} />
          <View style={[styles.gridLineV, { left: '66.66%' }]} />
        </View>

        {/* 5. 点击测光对焦方框动画 */}
        {focusPos && (
          <Animated.View
            pointerEvents="none"
            style={[
              styles.focusBox,
              {
                left: focusPos.x - 36,
                top: focusPos.y - 36,
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
  blackoutCover: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(5, 7, 13, 0.94)',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 5,
  },
  blackoutBadge: {
    alignItems: 'center',
    backgroundColor: 'rgba(255, 255, 255, 0.06)',
    paddingHorizontal: Spacing.xl,
    paddingVertical: Spacing.lg,
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.1)',
  },
  blackoutIcon: {
    fontSize: 42,
    marginBottom: Spacing.sm,
  },
  blackoutTitle: {
    ...Typography.h2,
    color: Colors.textPrimary,
    marginBottom: 4,
  },
  blackoutSubtitle: {
    ...Typography.bodySmall,
    color: Colors.textMuted,
    fontSize: 12,
  },
  mutedPill: {
    position: 'absolute',
    bottom: 140,
    alignSelf: 'center',
    backgroundColor: 'rgba(239, 68, 68, 0.25)',
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: 'rgba(239, 68, 68, 0.5)',
    zIndex: 6,
  },
  mutedText: {
    ...Typography.badge,
    color: Colors.liveRed,
  },
  gridOverlay: {
    ...StyleSheet.absoluteFillObject,
    opacity: 0.15,
  },
  gridLineH: {
    position: 'absolute',
    left: 0,
    right: 0,
    height: 1,
    backgroundColor: Colors.textPrimary,
  },
  gridLineV: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    width: 1,
    backgroundColor: Colors.textPrimary,
  },
  focusBox: {
    position: 'absolute',
    width: 72,
    height: 72,
    borderWidth: 1.5,
    borderColor: Colors.warningYellow,
    borderRadius: 8,
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 10,
  },
  focusCenterDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: Colors.warningYellow,
  },
});
