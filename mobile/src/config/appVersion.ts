/**
 * ==============================================================================
 * 智播豆移动端 (Zlive Mobile) - 软件版本与发布构建信息配置
 * ==============================================================================
 * 
 * ⚠️【开发者发布须知 / 版本更新维护入口】
 * 本文件是移动客户端版本号、编译构建时间及版权所属信息的唯一真实信息源（Single Source of Truth）。
 * 此处所有信息均写死在客户端代码内部，完全独立于后端 API 与网络连接。
 * 
 * 每一次发布新版本或更新应用时，只需在此修改以下常量字段：
 * 1. VERSION: 软件对外展示版本号 (如 'v1.0.0'、'v1.0.1')
 * 2. BUILD_NUMBER: 内部递增构建编号 (如 100, 101, 102)
 * 3. BUILD_TIME: 本次编译/构建打包时间 (格式建议: YYYY-MM-DD HH:mm:ss)
 * 4. COPYRIGHT: 版权所属主体与域名 (例如: 'graddu.com')
 * 5. RELEASE_NOTES: 本次版本更新概要摘要
 * ==============================================================================
 */

export interface AppVersionConfig {
  /** 软件官方中文名称 */
  appName: string;
  /** 软件官方英文名称/品牌 */
  appBrand: string;
  /** 软件对外版本号 (Semantic Version) */
  version: string;
  /** 内部构建版本代码 (Build Code) */
  buildNumber: number;
  /** 编译/构建发布时间 (YYYY-MM-DD HH:mm:ss) */
  buildTime: string;
  /** 版权所属主体 */
  copyright: string;
  /** 官方主页网址 */
  officialWebsite: string;
  /** 研发团队/发行单位 */
  developer: string;
  /** 构建环境 (Release 生产版 / Debug 测试版) */
  buildType: 'Release' | 'Debug';
  /** 核心音视频编解码与推流引擎规范 */
  engineVersion: string;
  /** 本版本发布摘要 */
  releaseNotes: string;
}

export const APP_VERSION_CONFIG: AppVersionConfig = {
  appName: '智播豆 · 移动推流客户端',
  appBrand: 'Zlive Mobile',
  version: 'v1.0.1',
  buildNumber: 101,
  buildTime: '2026-09-10 15:40:00',
  copyright: 'graddu.com',
  officialWebsite: 'https://graddu.com',
  developer: 'graddu.com 研发团队',
  buildType: 'Release',
  engineVersion: 'RootEncoder 2.5.0 / PDK H.264 Core',
  releaseNotes: '升级Android全套自适应桌面图标与前台层、优化Z字重心平衡、胶囊导航与矢量显隐组件',
};

/**
 * 完整版本标识字符串，例: "v1.0.0 (Build 100)"
 */
export const getFormattedVersion = (): string => {
  return `${APP_VERSION_CONFIG.version} (Build ${APP_VERSION_CONFIG.buildNumber})`;
};

/**
 * 版权声明文本，例: "版权所属：graddu.com · 保留所有权利"
 */
export const getCopyrightNotice = (): string => {
  return `版权所属：${APP_VERSION_CONFIG.copyright} · 保留所有权利`;
};

/**
 * 英文标准版权声明，例: "Copyright © 2026 graddu.com. All Rights Reserved."
 */
export const getFullEnglishCopyright = (): string => {
  return `Copyright © 2026 ${APP_VERSION_CONFIG.copyright}. All Rights Reserved.`;
};
