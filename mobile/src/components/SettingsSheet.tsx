import React from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableOpacity,
  Modal,
  ScrollView,
} from 'react-native';
import { Colors } from '../theme/colors';
import { Typography, Radius, Spacing } from '../theme/typography';
import { PdkEnv, VideoAudioSettings, VideoResolutionPreset } from '../api/types';
import { APP_VERSION_CONFIG } from '../config/appVersion';

export const RESOLUTION_PRESETS: VideoResolutionPreset[] = [
  { id: '1080p', name: '1080P 超清', width: 1080, height: 1920, label: '1080P' },
  { id: '720p', name: '720P 高清', width: 720, height: 1280, label: '720P' },
  { id: '540p', name: '540P 标清', width: 540, height: 960, label: '540P' },
];

export const BITRATE_PRESETS = [
  { label: '1800 kbps (推荐 · 弱网流畅)', value: 1800 },
  { label: '3500 kbps (高清 · 标杆画质)', value: 3500 },
  { label: '6000 kbps (超清 · 旗舰画质)', value: 6000 },
];

export const FPS_PRESETS = [
  { label: '30 FPS (通用标准推荐)', value: 30 },
  { label: '60 FPS (丝滑极高帧率)', value: 60 },
];

interface SettingsSheetProps {
  visible: boolean;
  settings: VideoAudioSettings;
  currentEnv?: PdkEnv;
  onUpdateSettings: (newSettings: Partial<VideoAudioSettings>) => void;
  onUpdateEnv?: (env: PdkEnv) => void;
  onClose: () => void;
}

/**
 * 底部毛玻璃画质与音视频编码设置抽屉
 */
export const SettingsSheet: React.FC<SettingsSheetProps> = ({
  visible,
  settings,
  onUpdateSettings,
  onClose,
}) => {
  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <View style={styles.modalBackdrop}>
        <TouchableOpacity
          style={styles.backdropClickArea}
          activeOpacity={1}
          onPress={onClose}
        />
        <View style={styles.sheetContainer}>
          {/* 顶部指示条与标题 */}
          <View style={styles.header}>
            <View style={styles.dragIndicator} />
            <View style={styles.headerRow}>
              <Text style={styles.headerTitle}>⚙️ 音视频编码与推流画质设置</Text>
              <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
                <Text style={styles.closeBtnText}>✕</Text>
              </TouchableOpacity>
            </View>
          </View>

          <ScrollView style={styles.contentScroll} showsVerticalScrollIndicator={false}>
            {/* 1. 分辨率选择 */}
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>推流画质分辨率</Text>
              <View style={styles.chipsRow}>
                {RESOLUTION_PRESETS.map((res) => {
                  const isSelected = settings.resolution.id === res.id;
                  return (
                    <TouchableOpacity
                      key={res.id}
                      style={[styles.chip, isSelected && styles.chipActive]}
                      onPress={() => onUpdateSettings({ resolution: res })}
                    >
                      <Text style={[styles.chipText, isSelected && styles.chipTextActive]}>
                        {res.name}
                      </Text>
                    </TouchableOpacity>
                  );
                })}
              </View>
            </View>

            {/* 2. 视频编码码率 */}
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>视频上行码率 (Bitrate)</Text>
              <View style={styles.chipsCol}>
                {BITRATE_PRESETS.map((item) => {
                  const isSelected = settings.bitrateKbps === item.value;
                  return (
                    <TouchableOpacity
                      key={item.value}
                      style={[styles.chipFull, isSelected && styles.chipActive]}
                      onPress={() => onUpdateSettings({ bitrateKbps: item.value })}
                    >
                      <Text style={[styles.chipText, isSelected && styles.chipTextActive]}>
                        {item.label}
                      </Text>
                    </TouchableOpacity>
                  );
                })}
              </View>
            </View>

            {/* 3. 编码帧率 */}
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>推流帧率 (FPS)</Text>
              <View style={styles.chipsRow}>
                {FPS_PRESETS.map((fps) => {
                  const isSelected = settings.fps === fps.value;
                  return (
                    <TouchableOpacity
                      key={fps.value}
                      style={[styles.chip, isSelected && styles.chipActive]}
                      onPress={() => onUpdateSettings({ fps: fps.value })}
                    >
                      <Text style={[styles.chipText, isSelected && styles.chipTextActive]}>
                        {fps.label}
                      </Text>
                    </TouchableOpacity>
                  );
                })}
              </View>
            </View>

            {/* 软件版本与版权备案落款 */}
            <View style={styles.versionFooter}>
              <Text style={styles.versionFooterText}>
                {APP_VERSION_CONFIG.appBrand} {APP_VERSION_CONFIG.version} · 编译时间 {APP_VERSION_CONFIG.buildTime}
              </Text>
              <Text style={styles.copyrightFooterText}>
                版权所属：{APP_VERSION_CONFIG.copyright}
              </Text>
            </View>

            <View style={{ height: 30 }} />
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.65)',
    justifyContent: 'flex-end',
  },
  backdropClickArea: {
    flex: 1,
  },
  sheetContainer: {
    backgroundColor: Colors.surface,
    borderTopLeftRadius: Radius.lg,
    borderTopRightRadius: Radius.lg,
    maxHeight: '75%',
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
    borderBottomWidth: 0,
    paddingHorizontal: Spacing.lg,
    paddingBottom: Spacing.xl,
  },
  header: {
    alignItems: 'center',
    paddingTop: Spacing.sm,
    paddingBottom: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.divider,
  },
  dragIndicator: {
    width: 36,
    height: 4,
    borderRadius: 2,
    backgroundColor: Colors.surfaceHover,
    marginBottom: Spacing.sm,
  },
  headerRow: {
    width: '100%',
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  headerTitle: {
    ...Typography.h3,
    color: Colors.textPrimary,
  },
  closeBtn: {
    padding: 6,
  },
  closeBtnText: {
    color: Colors.textSecondary,
    fontSize: 16,
    fontWeight: '700',
  },
  contentScroll: {
    marginTop: Spacing.md,
  },
  section: {
    marginBottom: Spacing.lg,
  },
  sectionTitle: {
    ...Typography.bodySmall,
    color: Colors.textSecondary,
    fontWeight: '600',
    marginBottom: Spacing.sm,
  },
  chipsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  chipsCol: {
    flexDirection: 'column',
    gap: 8,
  },
  chip: {
    flex: 1,
    marginHorizontal: 4,
    paddingVertical: 12,
    paddingHorizontal: 6,
    borderRadius: Radius.md,
    backgroundColor: Colors.surfaceSubtle,
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
    alignItems: 'center',
    justifyContent: 'center',
  },
  chipFull: {
    width: '100%',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: Radius.md,
    backgroundColor: Colors.surfaceSubtle,
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
  },
  chipActive: {
    backgroundColor: 'rgba(6, 182, 212, 0.15)',
    borderColor: Colors.primary,
  },
  chipActiveGreen: {
    backgroundColor: 'rgba(16, 185, 129, 0.15)',
    borderColor: Colors.onlineGreen,
  },
  chipActiveYellow: {
    backgroundColor: 'rgba(245, 158, 11, 0.15)',
    borderColor: Colors.warningYellow,
  },
  chipText: {
    ...Typography.body,
    color: Colors.textSecondary,
    fontSize: 13,
  },
  chipTextActive: {
    color: Colors.primary,
    fontWeight: '700',
  },
  chipTextActiveGreen: {
    color: Colors.onlineGreen,
    fontWeight: '700',
  },
  chipTextActiveYellow: {
    color: Colors.warningYellow,
    fontWeight: '700',
  },
  versionFooter: {
    alignItems: 'center',
    marginTop: Spacing.lg,
    paddingTop: Spacing.sm,
    borderTopWidth: 1,
    borderTopColor: Colors.divider,
  },
  versionFooterText: {
    ...Typography.bodySmall,
    color: Colors.textMuted,
    fontSize: 11,
    marginBottom: 3,
  },
  copyrightFooterText: {
    ...Typography.bodySmall,
    color: Colors.textMuted,
    fontSize: 11,
  },
});
