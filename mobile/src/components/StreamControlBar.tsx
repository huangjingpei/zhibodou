import React from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { Colors } from '../theme/colors';
import { Typography, Radius, Spacing } from '../theme/typography';

interface StreamControlBarProps {
  isStreaming: boolean;
  isLoading: boolean;
  isFrontCamera: boolean;
  isMuted: boolean;
  isVideoEnabled: boolean;
  onFlipCamera: () => void;
  onToggleMute: () => void;
  onToggleVideo: () => void;
  onOpenSettings: () => void;
  onToggleStream: () => void;
  onUserInteraction?: () => void;
}

/**
 * 现代化底部浮动音视频控制栏
 * 整合镜头翻转、麦克风静音、画面开关、参数抽屉与开播主控制
 */
export const StreamControlBar: React.FC<StreamControlBarProps> = ({
  isStreaming,
  isLoading,
  isFrontCamera,
  isMuted,
  isVideoEnabled,
  onFlipCamera,
  onToggleMute,
  onToggleVideo,
  onOpenSettings,
  onToggleStream,
  onUserInteraction,
}) => {
  const handlePress = (callback: () => void) => {
    onUserInteraction?.();
    callback();
  };

  return (
    <View style={styles.container}>
      {/* 上层：快捷功能圆形按钮栏 (镜头翻转、静音、画面开关、参数) */}
      <View style={styles.toolRow}>
        {/* 1. 镜头翻转 */}
        <TouchableOpacity
          style={styles.circleBtn}
          onPress={() => handlePress(onFlipCamera)}
          activeOpacity={0.7}
        >
          <Text style={styles.btnIcon}>🔄</Text>
          <Text style={styles.btnLabel}>{isFrontCamera ? '切后摄' : '切前摄'}</Text>
        </TouchableOpacity>

        {/* 2. 麦克风静音切换 */}
        <TouchableOpacity
          style={[styles.circleBtn, isMuted && styles.circleBtnActiveRed]}
          onPress={() => handlePress(onToggleMute)}
          activeOpacity={0.7}
        >
          <Text style={styles.btnIcon}>{isMuted ? '🔇' : '🎙️'}</Text>
          <Text style={[styles.btnLabel, isMuted && styles.btnLabelActiveRed]}>
            {isMuted ? '已静音' : '麦克风'}
          </Text>
        </TouchableOpacity>

        {/* 3. 画面开 / 关 (隐私黑屏遮蔽) */}
        <TouchableOpacity
          style={[
            styles.circleBtn,
            !isVideoEnabled && styles.circleBtnActiveRed,
          ]}
          onPress={() => handlePress(onToggleVideo)}
          activeOpacity={0.7}
        >
          <Text style={styles.btnIcon}>{isVideoEnabled ? '📹' : '🚫'}</Text>
          <Text
            style={[
              styles.btnLabel,
              !isVideoEnabled && styles.btnLabelActiveRed,
            ]}
          >
            {isVideoEnabled ? '画面开' : '画面关'}
          </Text>
        </TouchableOpacity>

        {/* 4. 参数设置面板 */}
        <TouchableOpacity
          style={styles.circleBtn}
          onPress={() => handlePress(onOpenSettings)}
          activeOpacity={0.7}
        >
          <Text style={styles.btnIcon}>⚙️</Text>
          <Text style={styles.btnLabel}>画质设置</Text>
        </TouchableOpacity>
      </View>

      {/* 下层：主直播开播/关播超宽操作胶囊按钮 */}
      <TouchableOpacity
        style={[
          styles.mainStreamBtn,
          isStreaming ? styles.mainBtnLive : styles.mainBtnStart,
          isLoading && styles.mainBtnLoading,
        ]}
        onPress={() => handlePress(onToggleStream)}
        disabled={isLoading}
        activeOpacity={0.85}
      >
        {isLoading ? (
          <View style={styles.loadingRow}>
            <ActivityIndicator color="#FFFFFF" size="small" />
            <Text style={styles.mainBtnText}>正在申请推流通道...</Text>
          </View>
        ) : (
          <View style={styles.btnContentRow}>
            <View
              style={[
                styles.liveActionDot,
                isStreaming ? styles.actionDotLive : styles.actionDotStart,
              ]}
            />
            <Text style={styles.mainBtnText}>
              {isStreaming ? '⏹ 结束当前直播推流' : '🔴 开始直播推流'}
            </Text>
          </View>
        )}
      </TouchableOpacity>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    gap: 16,
    width: '100%',
  },
  toolRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 18,
    backgroundColor: Colors.glassDark,
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: Radius.full,
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
  },
  circleBtn: {
    alignItems: 'center',
    justifyContent: 'center',
    width: 50,
    height: 50,
    borderRadius: 25,
    backgroundColor: 'rgba(255, 255, 255, 0.08)',
  },
  circleBtnActiveRed: {
    backgroundColor: 'rgba(239, 68, 68, 0.28)',
    borderWidth: 1,
    borderColor: Colors.liveRed,
  },
  circleBtnActiveYellow: {
    backgroundColor: 'rgba(245, 158, 11, 0.28)',
    borderWidth: 1,
    borderColor: Colors.warningYellow,
  },
  circleBtnDisabled: {
    opacity: 0.35,
  },
  btnIcon: {
    fontSize: 18,
    marginBottom: 2,
  },
  btnLabel: {
    ...Typography.badge,
    fontSize: 9,
    color: Colors.textSecondary,
  },
  btnLabelActiveRed: {
    color: Colors.liveRed,
    fontWeight: '700',
  },
  btnLabelActiveYellow: {
    color: Colors.warningYellow,
    fontWeight: '700',
  },
  btnLabelDisabled: {
    color: Colors.textMuted,
  },
  mainStreamBtn: {
    width: '100%',
    height: 52,
    borderRadius: Radius.full,
    justifyContent: 'center',
    alignItems: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.4,
    shadowRadius: 10,
    elevation: 8,
  },
  mainBtnStart: {
    backgroundColor: '#0EA5E9',
    borderWidth: 1,
    borderColor: '#38BDF8',
  },
  mainBtnLive: {
    backgroundColor: '#DC2626',
    borderWidth: 1,
    borderColor: '#F87171',
  },
  mainBtnLoading: {
    backgroundColor: Colors.surfaceSubtle,
  },
  btnContentRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  loadingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  liveActionDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  actionDotStart: {
    backgroundColor: '#FFFFFF',
  },
  actionDotLive: {
    backgroundColor: '#FCA5A5',
  },
  mainBtnText: {
    ...Typography.h3,
    color: '#FFFFFF',
    fontWeight: '700',
    letterSpacing: 0.5,
  },
});
