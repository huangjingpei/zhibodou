import React, { useEffect, useState } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableOpacity,
  Alert,
  ScrollView,
  ActivityIndicator,
} from 'react-native';
import { Colors } from '../theme/colors';
import { Typography, Radius, Spacing } from '../theme/typography';
import { pdkClient } from '../api/pdkClient';
import { deviceService } from '../services/deviceService';
import { DeviceLicense, LoginResult, UserProfile } from '../api/types';

interface ProfileScreenProps {
  loginResult: LoginResult;
  onBack: () => void;
  onLogout: () => void;
}

/**
 * 个人中心、设备许可证席位与解绑页面
 */
export const ProfileScreen: React.FC<ProfileScreenProps> = ({
  loginResult,
  onBack,
  onLogout,
}) => {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [license, setLicense] = useState<DeviceLicense | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const deviceId = deviceService.getDeviceId();

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setIsLoading(true);
    try {
      const [p, lic] = await Promise.allSettled([
        pdkClient.getUserProfile(),
        pdkClient.getDeviceLicenseCurrent(),
      ]);

      if (p.status === 'fulfilled') setProfile(p.value);
      if (lic.status === 'fulfilled') setLicense(lic.value);
    } finally {
      setIsLoading(false);
    }
  };

  const handleUnbind = () => {
    Alert.alert(
      '解绑设备',
      '确定要解绑当前手机设备吗？解绑后本台设备将释放席位，需在原卡密有效期内重新激活。',
      [
        { text: '取消', style: 'cancel' },
        {
          text: '确定解绑',
          style: 'destructive',
          onPress: async () => {
            try {
              await pdkClient.unbindDevice();
              Alert.alert('解绑成功', '本设备已成功解绑席位', [
                { text: '确定', onPress: onLogout },
              ]);
            } catch (err: any) {
              Alert.alert('解绑失败', err?.message || '无法解绑设备');
            }
          },
        },
      ]
    );
  };

  const handleLogout = () => {
    Alert.alert('退出登录', '确定要退出当前账号吗？', [
      { text: '取消', style: 'cancel' },
      {
        text: '退出',
        style: 'destructive',
        onPress: async () => {
          await pdkClient.logout().catch(() => {});
          onLogout();
        },
      },
    ]);
  };

  return (
    <View style={styles.container}>
      {/* 顶部导航栏 */}
      <View style={styles.header}>
        <TouchableOpacity onPress={onBack} style={styles.backBtn}>
          <Text style={styles.backBtnText}>‹ 返回直播室</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>账户与设备席位</Text>
        <View style={{ width: 60 }} />
      </View>

      <ScrollView contentContainerStyle={styles.scrollContent}>
        {isLoading ? (
          <ActivityIndicator color={Colors.primary} size="large" style={{ marginTop: 40 }} />
        ) : (
          <>
            {/* 1. 用户信息卡片 */}
            <View style={styles.card}>
              <View style={styles.userRow}>
                <View style={styles.avatar}>
                  <Text style={styles.avatarText}>👤</Text>
                </View>
                <View style={styles.userInfo}>
                  <Text style={styles.phoneText}>
                    {loginResult.phone || profile?.phone || '主播账号'}
                  </Text>
                  <Text style={styles.roleText}>智播推流主播 (AppId=3)</Text>
                </View>
              </View>
            </View>

            {/* 2. 当前设备许可证卡片 */}
            <View style={styles.card}>
              <Text style={styles.cardHeader}>📱 设备许可证与席位状态</Text>

              <View style={styles.itemRow}>
                <Text style={styles.itemLabel}>席位状态</Text>
                <View style={styles.statusBadgeActive}>
                  <Text style={styles.statusTextActive}>
                    {license?.status === 'ACTIVE' ? '已激活 (正常)' : license?.status || '正常'}
                  </Text>
                </View>
              </View>

              <View style={styles.itemRow}>
                <Text style={styles.itemLabel}>有效期至</Text>
                <Text style={styles.itemValue}>
                  {license?.expireAt || profile?.expireTime || '永久有效 / 未知'}
                </Text>
              </View>

              <View style={styles.itemRow}>
                <Text style={styles.itemLabel}>剩余调用次数</Text>
                <Text style={styles.itemValue}>
                  {profile?.remainingCalls !== undefined ? `${profile.remainingCalls} 次` : '不限'}
                </Text>
              </View>

              <View style={styles.divider} />

              <View style={styles.itemCol}>
                <Text style={styles.itemLabel}>设备唯一指纹 (UUID)</Text>
                <Text style={styles.deviceValueMono}>{deviceId}</Text>
              </View>
            </View>

            {/* 3. 操作操作按钮 */}
            <View style={styles.actionSection}>
              <TouchableOpacity
                style={styles.unbindBtn}
                onPress={handleUnbind}
                activeOpacity={0.7}
              >
                <Text style={styles.unbindBtnText}>🔓 解绑当前设备席位</Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={styles.logoutBtn}
                onPress={handleLogout}
                activeOpacity={0.7}
              >
                <Text style={styles.logoutBtnText}>🚪 退出当前登录</Text>
              </TouchableOpacity>
            </View>
          </>
        )}
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.background,
  },
  header: {
    paddingTop: 48,
    paddingBottom: Spacing.md,
    paddingHorizontal: Spacing.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: Colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderSubtle,
  },
  backBtn: {
    paddingVertical: 6,
    paddingHorizontal: 8,
  },
  backBtnText: {
    ...Typography.body,
    color: Colors.primary,
    fontWeight: '600',
  },
  headerTitle: {
    ...Typography.h3,
    color: Colors.textPrimary,
  },
  scrollContent: {
    padding: Spacing.lg,
  },
  card: {
    backgroundColor: Colors.surface,
    borderRadius: Radius.lg,
    padding: Spacing.lg,
    marginBottom: Spacing.lg,
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
  },
  userRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
  },
  avatar: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: Colors.surfaceSubtle,
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
    justifyContent: 'center',
    alignItems: 'center',
  },
  avatarText: {
    fontSize: 24,
  },
  userInfo: {
    flex: 1,
  },
  phoneText: {
    ...Typography.h3,
    color: Colors.textPrimary,
    marginBottom: 4,
  },
  roleText: {
    ...Typography.bodySmall,
    color: Colors.textSecondary,
  },
  cardHeader: {
    ...Typography.body,
    fontWeight: '700',
    color: Colors.textPrimary,
    marginBottom: Spacing.md,
  },
  itemRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 10,
  },
  itemCol: {
    paddingVertical: 8,
  },
  itemLabel: {
    ...Typography.body,
    color: Colors.textSecondary,
  },
  itemValue: {
    ...Typography.body,
    color: Colors.textPrimary,
    fontWeight: '600',
  },
  statusBadgeActive: {
    backgroundColor: 'rgba(16, 185, 129, 0.15)',
    borderWidth: 1,
    borderColor: Colors.onlineGreen,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: Radius.full,
  },
  statusTextActive: {
    ...Typography.badge,
    color: Colors.onlineGreen,
  },
  divider: {
    height: 1,
    backgroundColor: Colors.divider,
    marginVertical: Spacing.sm,
  },
  deviceValueMono: {
    ...Typography.mono,
    color: Colors.textSecondary,
    fontSize: 12,
    marginTop: 6,
  },
  actionSection: {
    gap: 12,
    marginTop: Spacing.md,
  },
  unbindBtn: {
    backgroundColor: 'rgba(245, 158, 11, 0.12)',
    borderWidth: 1,
    borderColor: 'rgba(245, 158, 11, 0.4)',
    height: 48,
    borderRadius: Radius.md,
    justifyContent: 'center',
    alignItems: 'center',
  },
  unbindBtnText: {
    ...Typography.body,
    color: Colors.warningYellow,
    fontWeight: '700',
  },
  logoutBtn: {
    backgroundColor: 'rgba(239, 68, 68, 0.12)',
    borderWidth: 1,
    borderColor: 'rgba(239, 68, 68, 0.4)',
    height: 48,
    borderRadius: Radius.md,
    justifyContent: 'center',
    alignItems: 'center',
  },
  logoutBtnText: {
    ...Typography.body,
    color: Colors.liveRed,
    fontWeight: '700',
  },
});
