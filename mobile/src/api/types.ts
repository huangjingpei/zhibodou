/**
 * PDK 协议与智播移动端核心数据结构体类型定义
 */

export enum PdkEnv {
  PRODUCTION = 'production',
  LOCAL_DEBUG = 'local_debug',
}

export interface PdkConfig {
  baseUrl: string;
  appId: number;
  bizCode: string;
  env: PdkEnv;
}

export interface ApiResponse<T = any> {
  code: number;
  message: string;
  data: T;
  timestamp?: number;
}

export interface LoginResult {
  tokenName: string;
  tokenValue: string;
  phone: string;
  userId?: number;
  authMode?: string;
  deviceLicense?: DeviceLicense;
}

export interface SessionVerifyResult {
  sessionValid: boolean;
  operationAllowedHint: boolean;
  status: string;
  expireAt: string;
  bizCode: string;
  authorizationMode: string;
}

export interface DeviceLicense {
  licenseId?: number;
  licenseCode?: string;
  status: 'ACTIVE' | 'SUSPENDED' | 'EXPIRED' | 'REVOKED' | 'UNKNOWN';
  deviceId: string;
  expireAt: string;
  maxStreams?: number;
  remainingCalls?: number;
  lastActiveAt?: string;
}

export interface UserProfile {
  userId?: number;
  bizId?: number;
  appId?: number;
  bizCode?: string;
  businessName?: string;
  businessDescription?: string;
  authorizationMode?: string;
  phone: string;
  maskedPhone?: string;
  status?: string;
  accountStatus?: string;
  deviceId?: string;
  packageName?: string;
  expireTime?: string;
  remainingCalls?: number;
  dailyCallsLimit?: number;
  maxAccounts?: number;
  role?: string;
  deviceLicense?: DeviceLicense;
}

export interface PushTicketResult {
  publishUrl: string;
  streamSessionNo: string;
  expiresAt: string;
  ticketTtlSeconds: number;
  status: string;
}

export interface StreamSessionInfo {
  streamSessionNo: string;
  title?: string;
  status: 'ISSUED' | 'AUTHORIZED' | 'LIVE' | 'ENDED';
  startedAt?: string;
  mediaServerAddress?: string;
}

export interface VideoResolutionPreset {
  id: string;
  name: string;
  width: number;
  height: number;
  label: string;
}

export interface VideoAudioSettings {
  resolution: VideoResolutionPreset;
  bitrateKbps: number;      // 视频码率 (kbps, 如 6000, 3500, 1800)
  fps: number;              // 帧率 (30 / 60)
  audioBitrateKbps: number; // 音频码率 (128 / 64)
  audioSampleRate: number;  // 48000 / 44100
  isMuted: boolean;         // 麦克风静音状态
  isFrontCamera: boolean;   // 是否为前置摄像头
  isTorchOn: boolean;       // 补光手电筒开关
  beautyLevel: number;      // 美颜磨皮等级 0-5
}
