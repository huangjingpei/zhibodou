import React, { useState, useRef } from 'react';
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
import { LoginResult } from '../api/types';
import { ZliveLogo } from '../components/ZliveLogo';
import { DevModeModal } from '../components/DevModeModal';
import { devSettingsService } from '../services/devSettingsService';
import { AgreementModal, AgreementType } from '../components/AgreementModal';
import { authStorageService } from '../services/authStorageService';

interface LoginScreenProps {
  onLoginSuccess: (result: LoginResult) => void;
}

/**
 * 现代暗色风格登录与工作站席位授权接入页面
 * 集成 Zlive 多彩品牌图标与合规协议验证
 * 支持连续点击 Logo 6 次呼出高级网络与流媒体设置
 * 支持“记住密码”安全沙盒持久化，提升日常推流工作便利性
 */
export const LoginScreen: React.FC<LoginScreenProps> = ({ onLoginSuccess }) => {
  const initialSaved = authStorageService.getSavedCredentials();
  const [phone, setPhone] = useState(initialSaved?.phone || '13800000000');
  const [password, setPassword] = useState(
    initialSaved?.rememberPassword && initialSaved?.password ? initialSaved.password : ''
  );
  const [rememberPassword, setRememberPassword] = useState(
    initialSaved !== null ? initialSaved.rememberPassword : true
  );
  const [showPassword, setShowPassword] = useState(false);
  const [cardKey, setCardKey] = useState('');
  const [needCardKey, setNeedCardKey] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  // 页面载入时：双通道读取原生私有安全沙盒中的账号与“记住密码”状态
  React.useEffect(() => {
    async function loadSavedCredentials() {
      try {
        const saved = await authStorageService.getSavedCredentialsAsync();
        if (saved) {
          if (saved.phone) setPhone(saved.phone);
          if (saved.rememberPassword) {
            setRememberPassword(true);
            if (saved.password) setPassword(saved.password);
          } else {
            setRememberPassword(false);
            setPassword('');
          }
        }
      } catch (e) {
        console.warn('[LoginScreen] 读取本地保存凭据异常:', e);
      }
    }
    loadSavedCredentials();
  }, []);

  // 用户服务协议与隐私政策合规状态
  const [agreedToTerms, setAgreedToTerms] = useState(false);
  const [agreementModalVisible, setAgreementModalVisible] = useState(false);
  const [agreementType, setAgreementType] = useState<AgreementType>('TERMS');

  // 连续轻点 Logo 6 次开启高级网络设置
  const [tapCount, setTapCount] = useState(0);
  const [devHint, setDevHint] = useState('');
  const [devModalVisible, setDevModalVisible] = useState(false);
  const tapTimerRef = useRef<NodeJS.Timeout | null>(null);

  const deviceId = deviceService.getDeviceId();

  const handleLogoPress = () => {
    if (tapTimerRef.current) {
      clearTimeout(tapTimerRef.current);
    }

    const nextCount = tapCount + 1;
    setTapCount(nextCount);

    if (nextCount >= 6) {
      setDevModalVisible(true);
      setTapCount(0);
      setDevHint('');
      return;
    }

    if (nextCount >= 3) {
      setDevHint(`已连续轻点 ${nextCount} 次，再点 ${6 - nextCount} 次开启高级网络设置`);
    }

    tapTimerRef.current = setTimeout(() => {
      setTapCount(0);
      setDevHint('');
    }, 3500);
  };

  const handleLogin = async () => {
    setErrorMessage('');

    // 合规性前置检查：必须同意用户协议与隐私政策
    if (!agreedToTerms) {
      setErrorMessage('请先阅读并勾选同意《用户服务协议》与《隐私保护政策》');
      return;
    }

    // 若高级网络设置配置了自定义 RTMP 直推地址，直接进入推流室
    if (devSettingsService.isDirectRtmp()) {
      authStorageService.saveCredentials({
        phone: phone.trim() || '13800000000',
        password: rememberPassword ? password : '',
        rememberPassword: rememberPassword,
        authMode: 'DIRECT_RTMP',
        lastLoginTime: Date.now(),
      });
      onLoginSuccess({
        tokenName: 'satoken',
        tokenValue: 'dev-direct-rtmp-token',
        phone: phone.trim() || '13800000000',
        authMode: 'DIRECT_RTMP',
      });
      return;
    }

    const targetPhone = phone.trim();
    const targetPassword = password.trim();

    if (!targetPhone) {
      setErrorMessage('请输入注册手机号');
      return;
    }
    if (!targetPassword) {
      setErrorMessage('请输入登录密码');
      return;
    }
    if (needCardKey && !cardKey.trim()) {
      setErrorMessage('新设备接入必须提供工作站席位授权码 (格式: PDK-...)');
      return;
    }

    setIsLoading(true);
    try {
      const res = await pdkClient.login(targetPhone, targetPassword, cardKey);
      // 登录成功：根据“记住密码”状态持久化到原生私有沙盒存储
      authStorageService.saveCredentials({
        phone: targetPhone,
        password: rememberPassword ? targetPassword : '',
        rememberPassword: rememberPassword,
        tokenName: res.tokenName,
        tokenValue: res.tokenValue,
        lastLoginTime: Date.now(),
      });
      onLoginSuccess(res);
    } catch (err: any) {
      if (err instanceof PdkClientError) {
        if (err.code === 40380) {
          setNeedCardKey(true);
          setErrorMessage('【新设备首次接入】请输入分配给本账号的席位授权码以绑定工作站');
        } else if (err.code === 40383) {
          setErrorMessage('【席位已被占用】该授权码已绑定其他终端，请先在原设备释放');
        } else if (err.code === 40381) {
          setErrorMessage('【工作站席位已到期】当前席位授权已到期，请联系管理员');
        } else {
          setErrorMessage(err.message || '登录失败，请核对信息');
        }
      } else {
        setErrorMessage(err?.message || '网络连接异常，请检查网络设置');
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
        {/* 品牌标识与标题 (连续点击 Logo 6 次触发高级网络设置) */}
        <View style={styles.brandHeader}>
          <TouchableOpacity
            activeOpacity={0.8}
            onPress={handleLogoPress}
            style={styles.logoTouchArea}
          >
            <View style={styles.logoCircle}>
              <ZliveLogo size={76} />
            </View>
          </TouchableOpacity>

          {devHint ? (
            <View style={styles.devHintBadge}>
              <Text style={styles.devHintText}>🛠️ {devHint}</Text>
            </View>
          ) : null}

          <Text style={styles.title}>Zlive · 智播云控</Text>
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
            <View style={styles.passwordInputContainer}>
              <TextInput
                style={[styles.textInput, styles.passwordInput]}
                placeholder="请输入密码"
                placeholderTextColor={Colors.textMuted}
                value={password}
                onChangeText={setPassword}
                secureTextEntry={!showPassword}
                autoCapitalize="none"
              />
              <TouchableOpacity
                style={styles.eyeBtn}
                onPress={() => setShowPassword(!showPassword)}
                activeOpacity={0.7}
              >
                <Text style={styles.eyeBtnText}>{showPassword ? '👁️' : '🙈'}</Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* 记住密码勾选选项 (合规自愿选择) */}
          <View style={styles.rememberRow}>
            <TouchableOpacity
              style={styles.checkboxTouch}
              onPress={() => setRememberPassword(!rememberPassword)}
              activeOpacity={0.7}
            >
              <View style={[styles.checkbox, rememberPassword && styles.checkboxChecked]}>
                {rememberPassword && <Text style={styles.checkboxCheckmark}>✓</Text>}
              </View>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => setRememberPassword(!rememberPassword)}
              activeOpacity={0.7}
            >
              <Text style={styles.rememberText}>记住密码（下次免手动输入）</Text>
            </TouchableOpacity>
          </View>

          {/* 新设备首次接入席位授权码输入区 (40380 自动触发) */}
          {needCardKey && (
            <View style={[styles.inputGroup, styles.cardKeyHighlight]}>
              <View style={styles.cardKeyHeaderRow}>
                <Text style={styles.cardKeyLabel}>工作站席位授权码 (接入绑定)</Text>
                <Text style={styles.badgeNewDevice}>新工作站</Text>
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
            <Text style={styles.deviceLabel}>工作站标识:</Text>
            <Text style={styles.deviceValue}>{deviceId}</Text>
          </View>

          {/* 隐私政策与服务协议勾选合规区 */}
          <View style={styles.agreementRow}>
            <TouchableOpacity
              style={styles.checkboxTouch}
              onPress={() => setAgreedToTerms(!agreedToTerms)}
              activeOpacity={0.7}
            >
              <View style={[styles.checkbox, agreedToTerms && styles.checkboxChecked]}>
                {agreedToTerms && <Text style={styles.checkboxCheckmark}>✓</Text>}
              </View>
            </TouchableOpacity>
            <View style={styles.agreementTextWrapper}>
              <Text style={styles.agreementLabel}>我已阅读并同意</Text>
              <TouchableOpacity
                onPress={() => {
                  setAgreementType('TERMS');
                  setAgreementModalVisible(true);
                }}
              >
                <Text style={styles.agreementLink}>《用户服务协议》</Text>
              </TouchableOpacity>
              <Text style={styles.agreementLabel}>与</Text>
              <TouchableOpacity
                onPress={() => {
                  setAgreementType('PRIVACY');
                  setAgreementModalVisible(true);
                }}
              >
                <Text style={styles.agreementLink}>《隐私保护政策》</Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* 登录/接入提交主按钮 */}
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
                {needCardKey ? '绑定授权并进入工作台' : '登 录 / 进 入'}
              </Text>
            )}
          </TouchableOpacity>
        </View>
      </ScrollView>

      {/* 高级网络与流媒体设置弹窗 */}
      <DevModeModal
        visible={devModalVisible}
        onClose={() => setDevModalVisible(false)}
        onDirectEnter={() => {
          setDevModalVisible(false);
          onLoginSuccess({
            tokenName: 'satoken',
            tokenValue: 'dev-direct-rtmp-token',
            phone: phone.trim() || '13800000000',
            authMode: 'DIRECT_RTMP',
          });
        }}
      />

      {/* 用户协议与隐私保护政策富文本展示弹窗 */}
      <AgreementModal
        visible={agreementModalVisible}
        type={agreementType}
        onClose={() => setAgreementModalVisible(false)}
        onAccept={() => {
          setAgreedToTerms(true);
          setAgreementModalVisible(false);
        }}
      />
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
  brandHeader: {
    alignItems: 'center',
    marginBottom: Spacing.xl,
  },
  logoTouchArea: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoCircle: {
    width: 80,
    height: 80,
    borderRadius: 22,
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.1)',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: Spacing.md,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.35,
    shadowRadius: 12,
    elevation: 6,
  },
  devHintBadge: {
    backgroundColor: 'rgba(245, 158, 11, 0.15)',
    borderWidth: 1,
    borderColor: Colors.warningYellow,
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: Radius.full,
    marginBottom: Spacing.sm,
  },
  devHintText: {
    ...Typography.bodySmall,
    fontSize: 11,
    color: Colors.warningYellow,
    fontWeight: '600',
  },
  title: {
    ...Typography.h1,
    color: Colors.textPrimary,
    marginBottom: 6,
    letterSpacing: 0.5,
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
  passwordInputContainer: {
    position: 'relative',
    justifyContent: 'center',
  },
  passwordInput: {
    paddingRight: 48,
  },
  eyeBtn: {
    position: 'absolute',
    right: 12,
    height: 48,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 4,
  },
  eyeBtnText: {
    fontSize: 18,
  },
  rememberRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: Spacing.sm,
    marginTop: 2,
  },
  rememberText: {
    ...Typography.bodySmall,
    color: Colors.textSecondary,
    fontSize: 12,
    fontWeight: '500',
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
  agreementRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: Spacing.sm,
    marginBottom: 4,
  },
  checkboxTouch: {
    padding: 4,
    marginRight: 4,
  },
  checkbox: {
    width: 18,
    height: 18,
    borderRadius: 4,
    borderWidth: 1.5,
    borderColor: Colors.borderSubtle,
    backgroundColor: Colors.surfaceSubtle,
    justifyContent: 'center',
    alignItems: 'center',
  },
  checkboxChecked: {
    backgroundColor: Colors.primary,
    borderColor: Colors.primary,
  },
  checkboxCheckmark: {
    color: '#FFFFFF',
    fontSize: 11,
    fontWeight: '900',
    lineHeight: 12,
  },
  agreementTextWrapper: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    flex: 1,
  },
  agreementLabel: {
    ...Typography.caption,
    color: Colors.textSecondary,
    fontSize: 11,
  },
  agreementLink: {
    ...Typography.caption,
    color: Colors.primary,
    fontSize: 11,
    fontWeight: '600',
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
