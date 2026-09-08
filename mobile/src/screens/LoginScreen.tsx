import React, { useState } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
} from 'react-native';
import { Colors } from '../theme/colors';
import { Typography, Radius, Spacing } from '../theme/typography';
import { pdkClient, PdkClientError } from '../api/pdkClient';
import { deviceService } from '../services/deviceService';
import { LoginResult, PdkEnv } from '../api/types';

interface LoginScreenProps {
  onLoginSuccess: (result: LoginResult) => void;
}

/**
 * 现代暗色风格登录与设备卡密激活页面
 * 自动识别 40380 状态码并弹出专属卡密绑定激活层
 */
export const LoginScreen: React.FC<LoginScreenProps> = ({ onLoginSuccess }) => {
  const [phone, setPhone] = useState('13800000000');
  const [password, setPassword] = useState('13800000000');
  const [cardKey, setCardKey] = useState('PDK-0CFB-4792-B745');
  const [needCardKey, setNeedCardKey] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [env, setEnv] = useState<PdkEnv>(pdkClient.getEnvironment());
  const [localHost, setLocalHost] = useState('192.168.3.148:8080');

  const deviceId = deviceService.getDeviceId();

  const handleToggleEnv = () => {
    const nextEnv = env === PdkEnv.PRODUCTION ? PdkEnv.LOCAL_DEBUG : PdkEnv.PRODUCTION;
    setEnv(nextEnv);
    pdkClient.setEnvironment(
      nextEnv,
      nextEnv === PdkEnv.LOCAL_DEBUG ? `http://${localHost.trim()}` : undefined
    );
  };

  const handleLogin = async () => {
    setErrorMessage('');
    if (!phone.trim()) {
      setErrorMessage('请输入注册手机号');
      return;
    }
    if (!password.trim()) {
      setErrorMessage('请输入登录密码');
      return;
    }
    if (needCardKey && !cardKey.trim()) {
      setErrorMessage('新设备激活必须提供设备卡密 (格式: PDK-...)');
      return;
    }

    setIsLoading(true);
    try {
      const res = await pdkClient.login(phone, password, cardKey);
      onLoginSuccess(res);
    } catch (err: any) {
      if (err instanceof PdkClientError) {
        if (err.code === 40380) {
          setNeedCardKey(true);
          setErrorMessage('【新设备首次激活】请输入分配给本账号的设备卡密以绑定席位');
        } else if (err.code === 40383) {
          setErrorMessage('【卡密已被占用】该卡密已绑定其他设备，请先在原设备解绑');
        } else if (err.code === 40381) {
          setErrorMessage('【许可证已到期】当前设备许可证已到期，请续费后登录');
        } else {
          setErrorMessage(err.message || '登录失败，请核对信息');
        }
      } else {
        setErrorMessage(err?.message || '网络连接异常，请检查环境');
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.scrollContent} keyboardShouldPersistTaps="handled">
        {/* 顶部环境切换胶囊 */}
        <View style={styles.topBar}>
          <TouchableOpacity
            style={[
              styles.envPill,
              env === PdkEnv.PRODUCTION ? styles.envProd : styles.envLocal,
            ]}
            onPress={handleToggleEnv}
          >
            <Text style={styles.envPillText}>
              {env === PdkEnv.PRODUCTION
                ? '🚀 生产环境 (pdk.graddu.com)'
                : `🛠️ 本地调试 (${localHost.trim() || '192.168.3.148:8080'})`}
            </Text>
          </TouchableOpacity>

          {env === PdkEnv.LOCAL_DEBUG && (
            <View style={styles.debugHostBox}>
              <Text style={styles.debugHostLabel}>调试机 IP:端口 (开发PC局域网地址)</Text>
              <TextInput
                style={styles.debugHostInput}
                value={localHost}
                onChangeText={(text) => {
                  setLocalHost(text);
                  pdkClient.setBaseUrl(`http://${text.trim()}`);
                }}
                placeholder="192.168.3.148:8080"
                placeholderTextColor={Colors.textMuted}
                autoCapitalize="none"
                keyboardType="url"
              />
            </View>
          )}
        </View>

        {/* 品牌标识与标题 */}
        <View style={styles.brandHeader}>
          <View style={styles.logoCircle}>
            <Text style={styles.logoIcon}>📡</Text>
          </View>
          <Text style={styles.title}>智播云控 · 移动端</Text>
          <Text style={styles.subtitle}>跨平台高清音视频推流与设备许可证中心</Text>
        </View>

        {/* 登录主体卡片 */}
        <View style={styles.card}>
          {/* 错误提示浮条 */}
          {errorMessage ? (
            <View style={styles.errorBanner}>
              <Text style={styles.errorText}>{errorMessage}</Text>
            </View>
          ) : null}

          {/* 手机号输入框 */}
          <View style={styles.inputGroup}>
            <Text style={styles.inputLabel}>手机账号</Text>
            <TextInput
              style={styles.textInput}
              placeholder="请输入手机号"
              placeholderTextColor={Colors.textMuted}
              value={phone}
              onChangeText={setPhone}
              keyboardType="phone-pad"
              autoCapitalize="none"
            />
          </View>

          {/* 密码输入框 */}
          <View style={styles.inputGroup}>
            <Text style={styles.inputLabel}>登录密码</Text>
            <TextInput
              style={styles.textInput}
              placeholder="请输入密码"
              placeholderTextColor={Colors.textMuted}
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              autoCapitalize="none"
            />
          </View>

          {/* 新设备激活卡密输入区 (40380 自动激活触发) */}
          {needCardKey && (
            <View style={[styles.inputGroup, styles.cardKeyHighlight]}>
              <View style={styles.cardKeyHeaderRow}>
                <Text style={styles.cardKeyLabel}>设备卡密 (席位绑定)</Text>
                <Text style={styles.badgeNewDevice}>新设备</Text>
              </View>
              <TextInput
                style={[styles.textInput, styles.cardKeyInput]}
                placeholder="PDK-XXXX-XXXX-XXXX"
                placeholderTextColor={Colors.textMuted}
                value={cardKey}
                onChangeText={setCardKey}
                autoCapitalize="characters"
              />
            </View>
          )}

          {/* 设备指纹唯一标识 */}
          <View style={styles.deviceRow}>
            <Text style={styles.deviceLabel}>本设备标识:</Text>
            <Text style={styles.deviceValue}>{deviceId}</Text>
          </View>

          {/* 登录/激活提交主按钮 */}
          <TouchableOpacity
            style={[styles.submitBtn, isLoading && styles.submitBtnDisabled]}
            onPress={handleLogin}
            disabled={isLoading}
            activeOpacity={0.85}
          >
            {isLoading ? (
              <ActivityIndicator color="#FFFFFF" />
            ) : (
              <Text style={styles.submitBtnText}>
                {needCardKey ? '立即激活并进入直播室' : '登 录 / 进 入'}
              </Text>
            )}
          </TouchableOpacity>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.background,
  },
  scrollContent: {
    flexGrow: 1,
    justifyContent: 'center',
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.xl,
  },
  topBar: {
    alignItems: 'center',
    marginBottom: Spacing.md,
  },
  envPill: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: Radius.full,
    borderWidth: 1,
  },
  envProd: {
    backgroundColor: 'rgba(16, 185, 129, 0.15)',
    borderColor: Colors.onlineGreen,
  },
  envLocal: {
    backgroundColor: 'rgba(245, 158, 11, 0.15)',
    borderColor: Colors.warningYellow,
  },
  envPillText: {
    ...Typography.mono,
    fontSize: 11,
    color: Colors.textPrimary,
  },
  debugHostBox: {
    marginTop: Spacing.sm,
    width: '100%',
    maxWidth: 320,
    backgroundColor: Colors.surfaceSubtle,
    borderRadius: Radius.md,
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
    padding: Spacing.sm,
    alignItems: 'center',
  },
  debugHostLabel: {
    color: Colors.warningYellow,
    fontSize: 10,
    marginBottom: 4,
  },
  debugHostInput: {
    backgroundColor: Colors.surface,
    color: Colors.textPrimary,
    ...Typography.mono,
    fontSize: 12,
    height: 34,
    borderRadius: Radius.sm,
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
    paddingHorizontal: 10,
    width: '100%',
    textAlign: 'center',
  },
  brandHeader: {
    alignItems: 'center',
    marginBottom: Spacing.xl,
  },
  logoCircle: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: 'rgba(6, 182, 212, 0.15)',
    borderWidth: 1.5,
    borderColor: Colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: Spacing.md,
  },
  logoIcon: {
    fontSize: 28,
  },
  title: {
    ...Typography.h1,
    color: Colors.textPrimary,
    marginBottom: 6,
  },
  subtitle: {
    ...Typography.bodySmall,
    color: Colors.textSecondary,
    textAlign: 'center',
  },
  card: {
    backgroundColor: Colors.surface,
    borderRadius: Radius.lg,
    padding: Spacing.lg,
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.3,
    shadowRadius: 20,
    elevation: 8,
  },
  errorBanner: {
    backgroundColor: 'rgba(244, 63, 94, 0.15)',
    borderWidth: 1,
    borderColor: Colors.errorRose,
    padding: Spacing.sm,
    borderRadius: Radius.md,
    marginBottom: Spacing.md,
  },
  errorText: {
    ...Typography.bodySmall,
    color: Colors.errorRose,
    lineHeight: 18,
  },
  inputGroup: {
    marginBottom: Spacing.md,
  },
  inputLabel: {
    ...Typography.bodySmall,
    color: Colors.textSecondary,
    marginBottom: 6,
    fontWeight: '600',
  },
  textInput: {
    backgroundColor: Colors.surfaceSubtle,
    borderRadius: Radius.md,
    height: 48,
    paddingHorizontal: 14,
    color: Colors.textPrimary,
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
    ...Typography.body,
  },
  cardKeyHighlight: {
    backgroundColor: 'rgba(245, 158, 11, 0.08)',
    padding: Spacing.sm,
    borderRadius: Radius.md,
    borderWidth: 1,
    borderColor: 'rgba(245, 158, 11, 0.35)',
  },
  cardKeyHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
  },
  cardKeyLabel: {
    ...Typography.bodySmall,
    color: Colors.warningYellow,
    fontWeight: '700',
  },
  badgeNewDevice: {
    ...Typography.badge,
    fontSize: 10,
    color: Colors.warningYellow,
    backgroundColor: 'rgba(245, 158, 11, 0.2)',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: Radius.sm,
  },
  cardKeyInput: {
    ...Typography.mono,
    letterSpacing: 1.2,
    borderColor: Colors.warningYellow,
  },
  deviceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginVertical: Spacing.sm,
    paddingVertical: 4,
  },
  deviceLabel: {
    ...Typography.bodySmall,
    color: Colors.textMuted,
  },
  deviceValue: {
    ...Typography.mono,
    fontSize: 11,
    color: Colors.textSecondary,
  },
  submitBtn: {
    backgroundColor: Colors.primary,
    height: 48,
    borderRadius: Radius.md,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: Spacing.md,
  },
  submitBtnDisabled: {
    opacity: 0.6,
  },
  submitBtnText: {
    ...Typography.h3,
    color: '#FFFFFF',
    fontWeight: '700',
  },
});
