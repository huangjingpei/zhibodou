import React, { useState } from 'react';
import {
  StyleSheet,
  View,
  Text,
  Modal,
  TouchableOpacity,
  ScrollView,
} from 'react-native';
import { Colors } from '../theme/colors';
import { Typography, Radius, Spacing } from '../theme/typography';

export type AgreementType = 'TERMS' | 'PRIVACY';

interface AgreementModalProps {
  visible: boolean;
  type: AgreementType;
  onClose: () => void;
  onAccept?: () => void;
}

export const AgreementModal: React.FC<AgreementModalProps> = ({
  visible,
  type,
  onClose,
  onAccept,
}) => {
  const [activeTab, setActiveTab] = useState<AgreementType>(type);

  // 同步外部传入的类型
  React.useEffect(() => {
    setActiveTab(type);
  }, [type]);

  const isTerms = activeTab === 'TERMS';

  return (
    <Modal visible={visible} animationType="slide" transparent>
      <View style={styles.backdrop}>
        <View style={styles.container}>
          {/* 顶部标签切换 */}
          <View style={styles.header}>
            <View style={styles.tabRow}>
              <TouchableOpacity
                style={[styles.tabBtn, isTerms && styles.tabBtnActive]}
                onPress={() => setActiveTab('TERMS')}
              >
                <Text style={[styles.tabText, isTerms && styles.tabTextActive]}>
                  用户服务协议
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.tabBtn, !isTerms && styles.tabBtnActive]}
                onPress={() => setActiveTab('PRIVACY')}
              >
                <Text style={[styles.tabText, !isTerms && styles.tabTextActive]}>
                  隐私保护政策
                </Text>
              </TouchableOpacity>
            </View>

            <TouchableOpacity onPress={onClose} style={styles.closeIconBtn}>
              <Text style={styles.closeIconText}>✕</Text>
            </TouchableOpacity>
          </View>

          {/* 协议正文内容 */}
          <ScrollView style={styles.contentScroll} showsVerticalScrollIndicator={true}>
            {isTerms ? (
              <View style={styles.textContainer}>
                <Text style={styles.title}>Zlive 软件许可与用户服务协议</Text>
                <Text style={styles.updatedDate}>更新日期：2026 年 3 月 1 日</Text>

                <Text style={styles.sectionTitle}>1. 导言与服务范围</Text>
                <Text style={styles.paragraph}>
                  欢迎使用 Zlive 智播云控系统（以下简称“本软件”）。本软件系面向企业广播操作员及授权直播技术人员提供的专业级多平台音视频推流工作站终端。
                </Text>

                <Text style={styles.sectionTitle}>2. 账号与席位授权许可</Text>
                <Text style={styles.paragraph}>
                  2.1 本软件的所有主播账号与工作站席位授权均由企业客户在企业管理中台统一部署与分配。用户应妥善保管个人工作账号及席位授权凭证。
                </Text>
                <Text style={styles.paragraph}>
                  2.2 严禁将本工作站授权码向任何未授权第三方转让、出租或分发。一个席位授权码在同一时间仅支持在一台授权移动工作站上激活运行。
                </Text>

                <Text style={styles.sectionTitle}>3. 推流内容与行为合规规范</Text>
                <Text style={styles.paragraph}>
                  用户在使用本软件采集音视频并向流媒体服务器推送实时流时，必须严格遵守国家法律法规及公序良俗，严禁推流任何违法、侵权、虚假或不良信息。
                </Text>

                <Text style={styles.sectionTitle}>4. 知识产权与免责声明</Text>
                <Text style={styles.paragraph}>
                  本软件的所有技术架构、图形设计、编解码优化算法均归属于本公司所有。因用户网络运营商抖动、第三方服务器断开等不可抗力导致的推流中断，本平台提供技术排查协助但不承担连带衍生损失。
                </Text>
              </View>
            ) : (
              <View style={styles.textContainer}>
                <Text style={styles.title}>Zlive 隐私保护政策与数据收集披露</Text>
                <Text style={styles.updatedDate}>更新日期：2026 年 3 月 1 日</Text>

                <Text style={styles.sectionTitle}>1. 我们收集的信息及目的</Text>
                <Text style={styles.paragraph}>
                  为向您提供高质量、稳定的音视频直播推流服务，依据《中华人民共和国个人信息保护法》及 Apple App Store 开发者隐私准则，我们仅收集实现推流功能所必须的最少限度数据：
                </Text>
                <Text style={styles.bulletItem}>
                  • <Text style={styles.boldText}>设备唯一指纹 (UUID / Keychain ID)</Text>：用于识别当前直播工作站硬件席位绑定状态，防止席位越权滥用。该标识符仅限本应用内部席位鉴权，绝不跨应用追踪或共享给任何第三方广告追踪网络。
                </Text>
                <Text style={styles.bulletItem}>
                  • <Text style={styles.boldText}>摄像头权限 (Camera Usage)</Text>：仅在您主动进入直播预览及启动开播时调用，用于本地视频画面的硬件采集与 H.264 编码推流，我们绝不在后台隐蔽调用相机。
                </Text>
                <Text style={styles.bulletItem}>
                  • <Text style={styles.boldText}>麦克风权限 (Microphone Usage)</Text>：仅在开播推流过程中采集现场音频并进行 AAC 高保真编码传输。在您关闭麦克风（静音）时音频采集立即切断。
                </Text>
                <Text style={styles.bulletItem}>
                  • <Text style={styles.boldText}>网络状态与诊断日志</Text>：用于实时监测推流上行带宽、丢包率与网络延迟（RTT），辅助您选择最优码率档位。
                </Text>

                <Text style={styles.sectionTitle}>2. 数据存储与安全保护</Text>
                <Text style={styles.paragraph}>
                  我们采用国际标准的 HTTPS/TLS 加密传输协议及 RSA-OAEP / AES-GCM 混合数字信封机制保障通信安全。您的设备标识存储于系统级安全沙盒（iOS Keychain / Android KeyStore）中。
                </Text>

                <Text style={styles.sectionTitle}>3. 用户权利与账号注销</Text>
                <Text style={styles.paragraph}>
                  您享有完全的个人数据自决权。您可随时在「个人中心」中主动解绑工作站设备席位，或点击「注销账号」彻底抹除当前账户在系统中的全部历史推流记录与授权关联。
                </Text>
              </View>
            )}
          </ScrollView>

          {/* 底部关闭/同意操作区 */}
          <View style={styles.footer}>
            {onAccept ? (
              <TouchableOpacity style={styles.acceptBtn} onPress={onAccept}>
                <Text style={styles.acceptBtnText}>已阅读并同意</Text>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity style={styles.closeBtn} onPress={onClose}>
                <Text style={styles.closeBtnText}>我知道了</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.75)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: Spacing.md,
  },
  container: {
    width: '100%',
    maxHeight: '82%',
    backgroundColor: Colors.surface,
    borderRadius: Radius.xl,
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
    overflow: 'hidden',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: Spacing.md,
    paddingTop: Spacing.md,
    paddingBottom: Spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderSubtle,
  },
  tabRow: {
    flexDirection: 'row',
    gap: 8,
  },
  tabBtn: {
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderRadius: Radius.full,
    backgroundColor: Colors.surfaceSubtle,
  },
  tabBtnActive: {
    backgroundColor: 'rgba(66, 133, 244, 0.15)',
    borderWidth: 1,
    borderColor: Colors.primary,
  },
  tabText: {
    ...Typography.bodySmall,
    color: Colors.textSecondary,
    fontWeight: '600',
  },
  tabTextActive: {
    color: Colors.primary,
    fontWeight: '700',
  },
  closeIconBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: Colors.surfaceSubtle,
    justifyContent: 'center',
    alignItems: 'center',
  },
  closeIconText: {
    color: Colors.textSecondary,
    fontSize: 16,
    fontWeight: '700',
  },
  contentScroll: {
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
  },
  textContainer: {
    paddingBottom: Spacing.xl,
  },
  title: {
    ...Typography.h3,
    color: Colors.textPrimary,
    marginBottom: 4,
  },
  updatedDate: {
    ...Typography.caption,
    color: Colors.textTertiary,
    marginBottom: Spacing.md,
  },
  sectionTitle: {
    ...Typography.body,
    fontWeight: '700',
    color: Colors.textPrimary,
    marginTop: Spacing.md,
    marginBottom: 6,
  },
  paragraph: {
    ...Typography.bodySmall,
    color: Colors.textSecondary,
    lineHeight: 20,
    marginBottom: 8,
  },
  bulletItem: {
    ...Typography.bodySmall,
    color: Colors.textSecondary,
    lineHeight: 20,
    marginBottom: 8,
    paddingLeft: 4,
  },
  boldText: {
    fontWeight: '700',
    color: Colors.textPrimary,
  },
  footer: {
    padding: Spacing.md,
    borderTopWidth: 1,
    borderTopColor: Colors.borderSubtle,
    backgroundColor: Colors.surface,
  },
  acceptBtn: {
    backgroundColor: Colors.primary,
    height: 46,
    borderRadius: Radius.md,
    justifyContent: 'center',
    alignItems: 'center',
  },
  acceptBtnText: {
    ...Typography.body,
    color: '#FFF',
    fontWeight: '700',
  },
  closeBtn: {
    backgroundColor: Colors.surfaceSubtle,
    borderWidth: 1,
    borderColor: Colors.borderSubtle,
    height: 46,
    borderRadius: Radius.md,
    justifyContent: 'center',
    alignItems: 'center',
  },
  closeBtnText: {
    ...Typography.body,
    color: Colors.textPrimary,
    fontWeight: '600',
  },
});
