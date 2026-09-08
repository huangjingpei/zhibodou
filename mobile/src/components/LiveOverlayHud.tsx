import React, { useEffect, useRef } from 'react';
import { StyleSheet, View, Text, TouchableOpacity, Animated } from 'react-native';
import { Colors } from '../theme/colors';
import { Typography, Radius, Spacing } from '../theme/typography';
import { StreamStats } from '../services/rtmpEngine';

interface LiveOverlayHudProps {
  isStreaming: boolean;
  stats: StreamStats;
  resolutionLabel: string;
  maskedPhone?: string;
  onProfilePress: () => void;
}

/**
 * 顶部悬浮流状态看板 HUD (Head-Up Display)
 * 具备实时闪烁 LIVE 徽标、推流时长计数器、上行码率/帧率动态指示与个人中心入口
 */
export const LiveOverlayHud: React.FC<LiveOverlayHudProps> = ({
  isStreaming,
  stats,
  resolutionLabel,
  maskedPhone = '未登录',
  onProfilePress,
}) => {
  const pulseAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (isStreaming) {
      Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, {
            toValue: 0.3,
            duration: 800,
            useNativeDriver: true,
          }),
          Animated.timing(pulseAnim, {
            toValue: 1,
            duration: 800,
            useNativeDriver: true,
          }),
        ])
      ).start();
    } else {
      pulseAnim.setValue(1);
    }
  }, [isStreaming, pulseAnim]);

  const formatDuration = (sec: number): string => {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    const pad = (n: number) => n.toString().padStart(2, '0');
    return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
  };

  return (
    <View style={styles.hudContainer}>
      {/* 左侧：直播状态徽标与时长 */}
      <View style={styles.leftSection}>
        <View style={[styles.statusBadge, isStreaming ? styles.badgeLive : styles.badgeIdle]}>
          <Animated.View
            style={[
              styles.statusDot,
              isStreaming ? styles.dotLive : styles.dotIdle,
              { opacity: isStreaming ? pulseAnim : 1 },
            ]}
          />
          <Text style={[styles.statusText, isStreaming ? styles.textLive : styles.textIdle]}>
            {isStreaming ? `LIVE ${formatDuration(stats.durationSeconds)}` : '待开播'}
          </Text>
        </View>

        {/* 动态性能数据胶囊 */}
        {isStreaming && (
          <View style={styles.statsPill}>
            <Text style={styles.statsText}>{resolutionLabel}</Text>
            <Text style={styles.statsDivider}>·</Text>
            <Text style={styles.statsText}>{stats.fps}fps</Text>
            <Text style={styles.statsDivider}>·</Text>
            <Text style={styles.statsText}>{stats.bitrateKbps}k</Text>
          </View>
        )}
      </View>

      {/* 右侧：用户信息胶囊入口 */}
      <TouchableOpacity
        style={styles.profileBtn}
        onPress={onProfilePress}
        activeOpacity={0.7}
      >
        <Text style={styles.profileIcon}>👤</Text>
        <Text style={styles.profilePhone}>{maskedPhone}</Text>
      </TouchableOpacity>
    </View>
  );
};

const styles = StyleSheet.create({
  hudContainer: {
    position: 'absolute',
    top: 48,
    left: Spacing.md,
    right: Spacing.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    zIndex: 10,
  },
  leftSection: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: Radius.full,
    borderWidth: 1,
  },
  badgeLive: {
    backgroundColor: 'rgba(239, 68, 68, 0.25)',
    borderColor: 'rgba(239, 68, 68, 0.5)',
  },
  badgeIdle: {
    backgroundColor: Colors.glassDark,
    borderColor: Colors.borderSubtle,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 6,
  },
  dotLive: {
    backgroundColor: Colors.liveRed,
  },
  dotIdle: {
    backgroundColor: Colors.textMuted,
  },
  statusText: {
    ...Typography.mono,
    fontSize: 12,
    fontWeight: '700',
  },
  textLive: {
    color: '#FFFFFF',
  },
  textIdle: {
    color: Colors.textSecondary,
  },
  statsPill: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Colors.glassDark,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: Radius.full,
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
  },
  statsText: {
    ...Typography.mono,
    fontSize: 11,
    color: Colors.textSecondary,
  },
  statsDivider: {
    marginHorizontal: 4,
    color: Colors.textMuted,
  },
  profileBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Colors.glassDark,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: Radius.full,
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
  },
  profileIcon: {
    fontSize: 12,
    marginRight: 5,
  },
  profilePhone: {
    ...Typography.bodySmall,
    color: Colors.textPrimary,
    fontWeight: '600',
  },
});
