import React, { useState, useEffect } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  Modal,
  ScrollView,
  Alert,
} from 'react-native';
import { Colors } from '../theme/colors';
import { Typography, Radius, Spacing } from '../theme/typography';
import { devSettingsService } from '../services/devSettingsService';

interface DevModeModalProps {
  visible: boolean;
  onClose: () => void;
  onSaved?: () => void;
  onDirectEnter?: () => void;
}

export const DevModeModal: React.FC<DevModeModalProps> = ({
  visible,
  onClose,
  onSaved,
  onDirectEnter,
}) => {
  const [serverUrl, setServerUrl] = useState('');
  const [customRtmpUrl, setCustomRtmpUrl] = useState('');

  useEffect(() => {
    if (visible) {
      const cfg = devSettingsService.getConfig();
      setServerUrl(cfg.serverUrl);
      setCustomRtmpUrl(cfg.customRtmpUrl);
    }
  }, [visible]);

  const handleSave = (showAlert = true) => {
    devSettingsService.saveConfig({
      serverUrl: serverUrl.trim() || 'https://pdk.graddu.com',
      customRtmpUrl: customRtmpUrl.trim(),
    });
    if (showAlert) {
      Alert.alert('网络流媒体设置已保存', '配置已实时持久化并生效', [
        {
          text: '确定',
          onPress: () => {
            onClose();
            onSaved?.();
          },
        },
      ]);
    } else {
      onSaved?.();
    }
  };

  const handleResetDefaults = () => {
    Alert.alert('重置配置', '确定要恢复为官方默认生产环境吗？', [
      { text: '取消', style: 'cancel' },
      {
        text: '恢复默认',
        style: 'destructive',
        onPress: () => {
          const cfg = devSettingsService.resetDefaults();
          setServerUrl(cfg.serverUrl);
          setCustomRtmpUrl(cfg.customRtmpUrl);
          Alert.alert('已恢复默认', '已重置为官方生产环境');
        },
      },
    ]);
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.modalBackdrop}>
        <TouchableOpacity style={styles.backdropClickArea} activeOpacity={1} onPress={onClose} />
        <View style={styles.sheetContainer}>
          {/* 顶部指示条与标题 */}
          <View style={styles.header}>
            <View style={styles.dragIndicator} />
            <View style={styles.headerRow}>
              <View style={styles.titleRow}>
                <Text style={styles.headerTitle}>🌐 高级网络与流媒体设置</Text>
                <View style={styles.devBadge}>
                  <Text style={styles.devBadgeText}>NETWORK</Text>
                </View>
              </View>
              <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
                <Text style={styles.closeBtnText}>✕</Text>
              </TouchableOpacity>
            </View>
          </View>

          <ScrollView style={styles.contentScroll} showsVerticalScrollIndicator={false}>
            {/* 1. 后端服务器地址配置 */}
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>后端 API 服务器地址</Text>
              <Text style={styles.sectionDesc}>
                应用交互的主服务地址。若不需要本地调试，保持默认官方地址即可。
              </Text>
              <TextInput
                style={styles.textInput}
                value={serverUrl}
                onChangeText={setServerUrl}
                placeholder="https://pdk.graddu.com"
                placeholderTextColor={Colors.textMuted}
                autoCapitalize="none"
                keyboardType="url"
              />
              <View style={styles.presetRow}>
                <TouchableOpacity
                  style={styles.presetChip}
                  onPress={() => setServerUrl('https://pdk.graddu.com')}
                >
                  <Text style={styles.presetChipText}>🚀 官方生产地址</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={styles.presetChip}
                  onPress={() => setServerUrl('http://192.168.3.148:8080')}
                >
                  <Text style={styles.presetChipText}>💻 本地局域网开发</Text>
                </TouchableOpacity>
              </View>
            </View>

            {/* 2. 自定义 RTMP 直推地址 (免后端直接推流) */}
            <View style={styles.section}>
              <View style={styles.sectionTitleRow}>
                <Text style={styles.sectionTitle}>自定义 RTMP 直推地址</Text>
                {customRtmpUrl.trim().length > 0 && (
                  <View style={styles.activeTag}>
                    <Text style={styles.activeTagText}>直推模式激活</Text>
                  </View>
                )}
              </View>
              <Text style={styles.sectionDescHighlight}>
                ⚠️ 特别说明：若在此填写了 RTMP 地址，开启直播将
                <Text style={{ fontWeight: '700', color: Colors.warningYellow }}>
                  【彻底跳过后端交互】
                </Text>
                直接推流至该 RTMP 服务端；若留空，则恢复通过业务后端申请票据推流。
              </Text>
              <TextInput
                style={[styles.textInput, customRtmpUrl.trim().length > 0 && styles.textInputActive]}
                value={customRtmpUrl}
                onChangeText={setCustomRtmpUrl}
                placeholder="rtmp://192.168.3.148:1935/live/test"
                placeholderTextColor={Colors.textMuted}
                autoCapitalize="none"
                keyboardType="url"
              />
              <View style={styles.presetRow}>
                {customRtmpUrl.trim().length > 0 ? (
                  <TouchableOpacity
                    style={styles.presetChipDanger}
                    onPress={() => setCustomRtmpUrl('')}
                  >
                    <Text style={styles.presetChipDangerText}>🗑️ 清空直推 (恢复后端票据)</Text>
                  </TouchableOpacity>
                ) : (
                  <TouchableOpacity
                    style={styles.presetChip}
                    onPress={() => setCustomRtmpUrl('rtmp://192.168.3.148:1935/live/test')}
                  >
                    <Text style={styles.presetChipText}>⚡ 填入本机局域网 RTMP 测试地址</Text>
                  </TouchableOpacity>
                )}
              </View>
            </View>

            {/* 底部按钮栏 */}
            <View style={styles.btnSection}>
              {Boolean(customRtmpUrl.trim()) && onDirectEnter && (
                <TouchableOpacity
                  style={styles.directEnterBtn}
                  onPress={() => {
                    handleSave(false);
                    onDirectEnter();
                  }}
                  activeOpacity={0.85}
                >
                  <Text style={styles.directEnterBtnText}>🚀 保存并进入专网直推工作台</Text>
                </TouchableOpacity>
              )}
              <TouchableOpacity style={styles.saveBtn} onPress={() => handleSave(true)} activeOpacity={0.85}>
                <Text style={styles.saveBtnText}>保存并应用设置</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.resetBtn}
                onPress={handleResetDefaults}
                activeOpacity={0.7}
              >
                <Text style={styles.resetBtnText}>恢复官方默认设置</Text>
              </TouchableOpacity>
            </View>

            <View style={{ height: 40 }} />
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'flex-end',
  },
  backdropClickArea: {
    flex: 1,
  },
  sheetContainer: {
    backgroundColor: Colors.surface,
    borderTopLeftRadius: Radius.lg,
    borderTopRightRadius: Radius.lg,
    borderTopWidth: 1,
    borderTopColor: Colors.borderSubtle,
    maxHeight: '85%',
    paddingBottom: Spacing.xl,
  },
  header: {
    alignItems: 'center',
    paddingTop: Spacing.sm,
    paddingBottom: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderSubtle,
  },
  dragIndicator: {
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: Colors.textMuted,
    marginBottom: Spacing.sm,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    width: '100%',
    paddingHorizontal: Spacing.lg,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  headerTitle: {
    ...Typography.h3,
    color: Colors.textPrimary,
  },
  devBadge: {
    backgroundColor: 'rgba(245, 158, 11, 0.15)',
    borderWidth: 1,
    borderColor: Colors.warningYellow,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: Radius.sm,
  },
  devBadgeText: {
    ...Typography.mono,
    fontSize: 9,
    color: Colors.warningYellow,
    fontWeight: '700',
  },
  closeBtn: {
    padding: Spacing.xs,
  },
  closeBtnText: {
    color: Colors.textMuted,
    fontSize: 18,
  },
  contentScroll: {
    paddingHorizontal: Spacing.lg,
    paddingTop: Spacing.md,
  },
  section: {
    marginBottom: Spacing.lg,
  },
  sectionTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  sectionTitle: {
    ...Typography.body,
    fontWeight: '700',
    color: Colors.textPrimary,
    marginBottom: 4,
  },
  activeTag: {
    backgroundColor: 'rgba(16, 185, 129, 0.2)',
    borderWidth: 1,
    borderColor: Colors.onlineGreen,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: Radius.full,
  },
  activeTagText: {
    ...Typography.badge,
    fontSize: 10,
    color: Colors.onlineGreen,
  },
  sectionDesc: {
    ...Typography.bodySmall,
    color: Colors.textSecondary,
    marginBottom: Spacing.sm,
    lineHeight: 18,
  },
  sectionDescHighlight: {
    ...Typography.bodySmall,
    color: Colors.textMuted,
    backgroundColor: 'rgba(245, 158, 11, 0.08)',
    borderLeftWidth: 3,
    borderLeftColor: Colors.warningYellow,
    padding: Spacing.sm,
    borderRadius: Radius.sm,
    marginBottom: Spacing.sm,
    lineHeight: 18,
  },
  textInput: {
    backgroundColor: Colors.surfaceSubtle,
    borderRadius: Radius.md,
    height: 48,
    paddingHorizontal: 14,
    color: Colors.textPrimary,
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
    ...Typography.mono,
    fontSize: 13,
  },
  textInputActive: {
    borderColor: Colors.onlineGreen,
    backgroundColor: 'rgba(16, 185, 129, 0.05)',
  },
  presetRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 8,
  },
  presetChip: {
    backgroundColor: Colors.surfaceSubtle,
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: Radius.sm,
  },
  presetChipText: {
    ...Typography.bodySmall,
    fontSize: 11,
    color: Colors.textSecondary,
  },
  presetChipDanger: {
    backgroundColor: 'rgba(239, 68, 68, 0.1)',
    borderWidth: 1,
    borderColor: 'rgba(239, 68, 68, 0.4)',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: Radius.sm,
  },
  presetChipDangerText: {
    ...Typography.bodySmall,
    fontSize: 11,
    color: Colors.liveRed,
    fontWeight: '600',
  },
  btnSection: {
    gap: 12,
    marginTop: Spacing.md,
  },
  saveBtn: {
    backgroundColor: Colors.primary,
    height: 48,
    borderRadius: Radius.md,
    justifyContent: 'center',
    alignItems: 'center',
  },
  saveBtnText: {
    ...Typography.h3,
    color: '#FFFFFF',
    fontWeight: '700',
  },
  resetBtn: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
    height: 44,
    borderRadius: Radius.md,
    justifyContent: 'center',
    alignItems: 'center',
  },
  resetBtnText: {
    ...Typography.body,
    color: Colors.textMuted,
  },
  directEnterBtn: {
    backgroundColor: '#059669',
    height: 48,
    borderRadius: Radius.md,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#34D399',
  },
  directEnterBtnText: {
    ...Typography.h3,
    color: '#FFFFFF',
    fontWeight: '700',
  },
});
