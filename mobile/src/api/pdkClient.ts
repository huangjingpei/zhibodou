import { Platform } from 'react-native';
import forge from 'node-forge';
import {
  ApiResponse,
  DeviceLicense,
  LoginResult,
  PdkConfig,
  PdkEnv,
  PushTicketResult,
  SessionVerifyResult,
  StreamSessionInfo,
  UserProfile,
} from './types';
import { deviceService } from '../services/deviceService';

export class PdkClientError extends Error {
  public code: number;
  public data: any;

  constructor(code: number, message: string, data?: any) {
    super(message);
    this.name = 'PdkClientError';
    this.code = code;
    this.data = data;
  }
}

function generateUuid(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function generateRandomString(length: number = 24): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let res = '';
  for (let i = 0; i < length; i++) {
    res += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return res;
}

/**
 * 标准 ECMAScript UTF-8 字符串转二进制字节串 (兼容 Hermes，完全脱离已废弃的 unescape)
 */
function utf8ToBinary(str: string): string {
  const encoded = encodeURIComponent(str);
  let bin = '';
  for (let i = 0; i < encoded.length; i++) {
    if (encoded[i] === '%') {
      bin += String.fromCharCode(parseInt(encoded.substring(i + 1, i + 3), 16));
      i += 2;
    } else {
      bin += encoded[i];
    }
  }
  return bin;
}

/**
 * 二进制字节串还原为标准 UTF-8 字符串 (兼容 Hermes，完全脱离已废弃的 escape)
 */
function binaryToUtf8(bin: string): string {
  let encoded = '';
  for (let i = 0; i < bin.length; i++) {
    encoded += '%' + bin.charCodeAt(i).toString(16).padStart(2, '0');
  }
  return decodeURIComponent(encoded);
}

export class PdkClient {
  private config: PdkConfig;
  private tokenName: string = 'satoken';
  private tokenValue: string = '';
  private phone: string = '';

  // 协议安全与信封加密状态
  private serverPublicKeyPem: string = '';
  private kid: string = 'v1';
  private encryptionMode: string = 'optional';
  private sessionKey: string | null = null; // 32 字节二进制 AES 密钥
  private useCrypto: boolean = false;

  public static readonly DEFAULT_LOCAL_URL = 'http://192.168.3.148:8080';
  public static readonly PRODUCTION_URL = 'https://pdk.graddu.com';

  constructor(env: PdkEnv = PdkEnv.PRODUCTION) {
    this.config = {
      baseUrl:
        env === PdkEnv.PRODUCTION
          ? PdkClient.PRODUCTION_URL
          : PdkClient.DEFAULT_LOCAL_URL,
      appId: 3,
      bizCode: 'ZHIBO_LIVE',
      env,
    };
  }

  public setEnvironment(env: PdkEnv, customUrl?: string): void {
    this.config.env = env;
    if (customUrl) {
      this.config.baseUrl = customUrl.replace(/\/+$/, '');
    } else {
      this.config.baseUrl =
        env === PdkEnv.PRODUCTION
          ? PdkClient.PRODUCTION_URL
          : PdkClient.DEFAULT_LOCAL_URL;
    }
    // 切换环境时彻底重置密钥缓存与旧环境会话，避免产生密钥不匹配(42904)
    this.serverPublicKeyPem = '';
    this.kid = 'v1';
    this.sessionKey = null;
    this.useCrypto = false;
    this.tokenValue = '';
  }

  public setBaseUrl(url: string): void {
    if (url) {
      this.config.baseUrl = url.replace(/\/+$/, '');
      this.serverPublicKeyPem = '';
      this.kid = 'v1';
      this.sessionKey = null;
      this.useCrypto = false;
      this.tokenValue = '';
    }
  }

  public getEnvironment(): PdkEnv {
    return this.config.env;
  }

  public getBaseUrl(): string {
    return this.config.baseUrl;
  }

  public setToken(name: string, value: string): void {
    this.tokenName = name || 'satoken';
    this.tokenValue = value || '';
  }

  public getTokenValue(): string {
    return this.tokenValue;
  }

  public setPhone(phone: string): void {
    this.phone = (phone || '').trim();
  }

  public getPhone(): string {
    return this.phone;
  }

  public isLoggedIn(): boolean {
    return Boolean(this.tokenValue);
  }

  public clearSession(): void {
    this.tokenValue = '';
    this.sessionKey = null;
  }

  public restoreSession(snapshot: {
    phone?: string;
    tokenName?: string;
    tokenValue?: string;
  }): void {
    if (snapshot.phone) this.phone = snapshot.phone.trim();
    if (snapshot.tokenName) this.tokenName = snapshot.tokenName;
    if (snapshot.tokenValue) this.tokenValue = snapshot.tokenValue;
  }

  /**
   * 构建统一请求头 (严格匹配服务端 DeviceSecurityInterceptor 与 ClientCryptoAdvice 规范)
   */
  private buildHeaders(
    authenticated: boolean,
    extraHeaders: Record<string, string> = {}
  ): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      'X-PDK-App-ID': String(this.config.appId),
      'X-PDK-Device-ID': deviceService.getDeviceId(),
      'User-Agent': `Zhibodou-Mobile/1.0.0 (${Platform.OS})`,
      ...extraHeaders,
    };

    // 关键鉴权头：用户手机号
    if (this.phone) {
      headers['X-PDK-Phone'] = this.phone;
    }

    // 声明客户端持有会话级 AES 密钥，服务端据此才会对响应进行信封加密
    if (this.sessionKey) {
      headers['X-PDK-Crypto-Armed'] = '1';
    }

    // 登录鉴权 Token
    if (authenticated) {
      if (!this.tokenValue) {
        throw new PdkClientError(40100, '本地没有完整登录会话，请先登录');
      }
      headers[this.tokenName] = this.tokenValue;
      headers['Authorization'] = `Bearer ${this.tokenValue}`;
      headers['Cookie'] = `${this.tokenName}=${this.tokenValue}`;
    }

    return headers;
  }

  /**
   * 判断一段文本是否为协议信封格式
   */
  private isEnvelope(text: string): boolean {
    if (!text || typeof text !== 'string') return false;
    try {
      const obj = JSON.parse(text);
      return (
        typeof obj === 'object' &&
        obj !== null &&
        'data' in obj &&
        'iv' in obj &&
        'kid' in obj
      );
    } catch {
      return false;
    }
  }

  /**
   * 使用 AES-256-GCM + RSA-OAEP 对请求体执行信封加密
   */
  private encryptBody(body: any): string {
    if (!this.serverPublicKeyPem) {
      throw new PdkClientError(42901, '服务端公钥未就绪，无法执行信封加密');
    }

    const aesKey = forge.random.getBytesSync(32);
    const iv = forge.random.getBytesSync(12);
    const plainText = JSON.stringify(body);
    const binaryPlain = utf8ToBinary(plainText);

    // 1. AES-256-GCM 对称加密 (tag 长度 16 字节 / 128 位)
    const cipher = forge.cipher.createCipher('AES-GCM', aesKey);
    cipher.start({ iv, tagLength: 128 });
    cipher.update(forge.util.createBuffer(binaryPlain));
    cipher.finish();

    const outputBytes = cipher.output.getBytes();
    const tagBytes = cipher.mode.tag.getBytes();
    const encryptedData = outputBytes + tagBytes;

    // 2. RSA-OAEP 非对称加密 (显式 SHA-256 MGF1，严格与服务端 BodyCryptoService 对齐)
    const publicKey = forge.pki.publicKeyFromPem(this.serverPublicKeyPem);
    const wrappedKey = publicKey.encrypt(aesKey, 'RSA-OAEP', {
      md: forge.md.sha256.create(),
      mgf1: { md: forge.md.sha256.create() },
    });

    // 记录本次会话密钥供响应解密复用
    this.sessionKey = aesKey;

    const envelope = {
      kid: this.kid,
      enc: forge.util.encode64(wrappedKey),
      iv: forge.util.encode64(iv),
      data: forge.util.encode64(encryptedData),
      ts: Date.now(),
      rnd: `m_${generateRandomString(22)}`,
    };

    return JSON.stringify(envelope);
  }

  /**
   * 解密服务端响应信封
   */
  private decryptResponse(envelopeText: string): string {
    if (!this.sessionKey) {
      throw new PdkClientError(
        42904,
        '收到加密响应，但本地没有对应的 AES 会话密钥'
      );
    }

    const envelope = JSON.parse(envelopeText);
    const rawData = forge.util.decode64(envelope.data);
    const iv = forge.util.decode64(envelope.iv);
    const tagLength = 16;
    const cipherText = rawData.slice(0, rawData.length - tagLength);
    const tag = rawData.slice(rawData.length - tagLength);

    const decipher = forge.cipher.createDecipher('AES-GCM', this.sessionKey);
    decipher.start({
      iv,
      tagLength: 128,
      tag: forge.util.createBuffer(tag),
    });
    decipher.update(forge.util.createBuffer(cipherText));
    const pass = decipher.finish();
    if (!pass) {
      throw new PdkClientError(42904, '响应信封解密认证失败');
    }

    return binaryToUtf8(decipher.output.getBytes());
  }

  /**
   * 通用网络请求核心封装
   */
  private async request<T = any>(
    method: 'GET' | 'POST' | 'PUT' | 'DELETE',
    path: string,
    body?: any,
    options: {
      authenticated?: boolean;
      headers?: Record<string, string>;
      isRetry?: boolean;
    } = {}
  ): Promise<T> {
    const { authenticated = false, headers = {}, isRetry = false } = options;
    const url = `${this.config.baseUrl}${path}`;

    // 非公开配置接口，确保先预取服务端安全配置（公钥与加密模式），避免首包明文被拒
    if (!this.serverPublicKeyPem && path !== '/api/v1/client/config/public') {
      try {
        await this.fetchPublicConfig();
      } catch (e) {
        console.warn('[PdkClient] 预先拉取加密公钥配置失败，将回落尝试发送:', e);
      }
    }

    // 优先处理请求体加密（先生成会话密钥，确保后续 buildHeaders 能正确携带 X-PDK-Crypto-Armed: 1）
    let reqBody: string | undefined = undefined;
    if (body !== undefined && (method === 'POST' || method === 'PUT')) {
      if (this.useCrypto && this.serverPublicKeyPem) {
        try {
          reqBody = this.encryptBody(body);
        } catch (err) {
          console.warn('[PdkClient] 信封加密失败，回落明文传输:', err);
          reqBody = JSON.stringify(body);
        }
      } else {
        reqBody = JSON.stringify(body);
      }
    }

    await deviceService.ensureDeviceId();
    const reqHeaders = this.buildHeaders(authenticated, headers);
    const fetchOptions: RequestInit = {
      method,
      headers: reqHeaders,
      body: reqBody,
    };

    let response: Response;
    try {
      response = await fetch(url, fetchOptions);
    } catch (err: any) {
      throw new PdkClientError(
        -1,
        `网络连接失败: ${err?.message || '无法连接到 PDK 服务端'}，请检查网络或切换环境`
      );
    }

    let rawText: string;
    try {
      rawText = await response.text();
    } catch {
      throw new PdkClientError(
        response.status,
        `无法读取服务端响应 (HTTP ${response.status})`
      );
    }

    // 检查是否为信封加密报文
    if (this.isEnvelope(rawText)) {
      try {
        rawText = this.decryptResponse(rawText);
      } catch (err: any) {
        throw new PdkClientError(
          42904,
          `解密服务端响应报文失败: ${err?.message || '未知错误'}`
        );
      }
    }

    let resJson: ApiResponse<T>;
    try {
      resJson = JSON.parse(rawText);
    } catch {
      throw new PdkClientError(
        response.status,
        `服务端响应格式异常 (HTTP ${response.status}): ${rawText.slice(0, 120)}`
      );
    }

    // 处理服务端安全协议重置码：42900(强制加密)、42901(kid版本失效)、42904(报文解密失败)
    // 自动清理本地公钥缓存，重新拉取服务端最新公钥并自愈重试一次
    if (
      (resJson.code === 42900 || resJson.code === 42901 || resJson.code === 42904) &&
      !isRetry
    ) {
      console.info(
        `[PdkClient] 收到安全协议重置响应 (${resJson.code}: ${resJson.message})，正在重新拉取最新公钥配置并重试...`
      );
      this.serverPublicKeyPem = '';
      this.sessionKey = null;
      this.useCrypto = true;
      await this.fetchPublicConfig(true);
      return this.request<T>(method, path, body, {
        authenticated,
        headers,
        isRetry: true,
      });
    }

    if (resJson.code !== 200 && resJson.code !== 0) {
      throw new PdkClientError(
        resJson.code || response.status,
        resJson.message || '业务请求失败',
        resJson.data
      );
    }

    return resJson.data;
  }

  /**
   * 1. 获取公共安全与环境配置 (拉取 RSA 公钥与 kid)
   */
  public async fetchPublicConfig(forceRefresh: boolean = false): Promise<any> {
    if (this.serverPublicKeyPem && !forceRefresh) {
      return {
        encryptionMode: this.encryptionMode,
        publicKey: this.serverPublicKeyPem,
        kid: this.kid,
      };
    }

    const data = await this.request<any>(
      'GET',
      '/api/v1/client/config/public',
      undefined,
      { authenticated: false }
    );

    if (data) {
      this.serverPublicKeyPem = data.publicKey || '';
      this.kid = data.kid || 'v1';
      this.encryptionMode = (data.encryptionMode || 'optional').toLowerCase();
      if (this.encryptionMode !== 'off') {
        this.useCrypto = true;
      }
    }

    return data;
  }

  /**
   * 2. 业务发现 (ZHIBO_LIVE / appId=3)
   */
  public async getBusinessInfo(): Promise<any> {
    return this.request(
      'GET',
      `/api/v1/client/business/by-app/${this.config.appId}`,
      undefined,
      { authenticated: false }
    );
  }

  /**
   * 3. 登录与设备绑定
   */
  public async login(
    phone: string,
    password: string,
    cardKey: string = ''
  ): Promise<LoginResult> {
    const targetPhone = phone.trim();
    this.phone = targetPhone;

    const deviceId = await deviceService.ensureDeviceId();
    const payload: Record<string, any> = {
      appId: this.config.appId,
      phone: targetPhone,
      password: password.trim(),
      deviceId,
      deviceName: 'Mobile App',
      platform: Platform.OS.toLowerCase(),
      clientVersion: '1.0.0',
    };

    if (cardKey && cardKey.trim()) {
      payload.cardKey = cardKey.trim();
    }

    const data = await this.request<any>(
      'POST',
      '/api/v1/client/auth/login',
      payload,
      { authenticated: false }
    );

    const tokenName = data.tokenName || 'satoken';
    const tokenValue = data.tokenValue || '';
    if (tokenValue) {
      this.setToken(tokenName, tokenValue);
    }

    return {
      tokenName,
      tokenValue,
      phone: targetPhone,
      userId: data.userId,
      authMode: data.authorizationMode || data.authMode,
      deviceLicense: data.deviceLicense,
    };
  }

  /**
   * 4. 会话有效性与权限校验
   */
  public async verifySession(): Promise<SessionVerifyResult> {
    const profile = await this.getUserProfile();
    const license = profile.deviceLicense;
    const isLicenseActive = license ? license.status === 'ACTIVE' : false;

    return {
      sessionValid: true,
      operationAllowedHint: isLicenseActive || profile.accountStatus === 'ACTIVE',
      status: license?.status || profile.accountStatus || 'UNKNOWN',
      expireAt: license?.expireAt || profile.expireTime || '',
      bizCode: this.config.bizCode,
      authorizationMode: profile.authorizationMode || 'DEVICE_LICENSE',
    };
  }

  /**
   * 5. 当前用户资料
   */
  public async getUserProfile(): Promise<UserProfile> {
    return this.request<UserProfile>(
      'GET',
      '/api/v1/client/account/profile',
      undefined,
      { authenticated: true }
    );
  }

  /**
   * 6. 当前设备许可证详情
   */
  public async getDeviceLicenseCurrent(): Promise<DeviceLicense> {
    return this.request<DeviceLicense>(
      'GET',
      '/api/v1/client/device-license/current',
      undefined,
      { authenticated: true }
    );
  }

  /**
   * 7. 申请短效 RTMP 推流票据
   */
  public async acquirePushTicket(
    title: string = '移动端智播推流'
  ): Promise<PushTicketResult> {
    const clientRequestId = generateUuid();
    return this.request<PushTicketResult>(
      'POST',
      '/api/v1/client/zhibo-live/publish-tickets',
      {
        clientRequestId,
        title,
        requestedProtocol: 'RTMP',
      },
      { authenticated: true }
    );
  }

  /**
   * 8. 停止当前流会话
   */
  public async stopStream(sessionNo: string): Promise<any> {
    if (!sessionNo) return;
    return this.request(
      'POST',
      `/api/v1/client/zhibo-live/streams/${encodeURIComponent(sessionNo)}/stop`,
      {},
      { authenticated: true }
    );
  }

  /**
   * 9. 查询当前账号关联的活动流
   */
  public async getCurrentStreams(): Promise<StreamSessionInfo[]> {
    return this.request<StreamSessionInfo[]>(
      'GET',
      '/api/v1/client/zhibo-live/streams/current',
      undefined,
      { authenticated: true }
    );
  }

  /**
   * 10. 设备解绑
   */
  public async unbindDevice(): Promise<any> {
    const result = await this.request(
      'POST',
      '/api/v1/client/device-license/unbind',
      {},
      { authenticated: true }
    );
    this.clearSession();
    return result;
  }

  /**
   * 11. 退出登录
   */
  public async logout(): Promise<any> {
    try {
      await this.request(
        'POST',
        '/api/v1/client/auth/logout',
        {},
        { authenticated: true }
      );
    } finally {
      this.clearSession();
    }
  }
}

// 导出全局单例 (默认接入官方生产环境 https://pdk.graddu.com)
export const pdkClient = new PdkClient(PdkEnv.PRODUCTION);
