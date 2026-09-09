import { NativeModules } from 'react-native';
import { pdkClient } from '../api/pdkClient';

export interface DevConfig {
  serverUrl: string;       // 后端 API 服务器地址，默认 https://pdk.graddu.com
  customRtmpUrl: string;   // 自定义 RTMP 直推地址 (非空时免后端直接推流)
}

const DEFAULT_DEV_CONFIG: DevConfig = {
  serverUrl: 'https://pdk.graddu.com',
  customRtmpUrl: '',
};

class DevSettingsService {
  private config: DevConfig = { ...DEFAULT_DEV_CONFIG };
  private initialized: boolean = false;

  constructor() {
    this.init();
  }

  private init(): void {
    if (this.initialized) return;
    try {
      const module = NativeModules?.PdkDeviceModule;
      if (module && typeof module.getDevConfigSync === 'function') {
        const raw = module.getDevConfigSync();
        if (raw && typeof raw === 'string' && raw.trim().length > 0) {
          const parsed = JSON.parse(raw);
          this.config = {
            serverUrl: (parsed.serverUrl || DEFAULT_DEV_CONFIG.serverUrl).trim(),
            customRtmpUrl: (parsed.customRtmpUrl || '').trim(),
          };
          this.applyToClient();
        }
      }
    } catch (e) {
      console.warn('[DevSettingsService] 加载持久化配置失败，使用默认值:', e);
    }
    this.initialized = true;
  }

  private applyToClient(): void {
    if (this.config.serverUrl) {
      pdkClient.setBaseUrl(this.config.serverUrl);
    }
  }

  public getConfig(): DevConfig {
    this.init();
    return { ...this.config };
  }

  public saveConfig(newConfig: Partial<DevConfig>): void {
    this.config = {
      serverUrl: (newConfig.serverUrl !== undefined ? newConfig.serverUrl : this.config.serverUrl).trim(),
      customRtmpUrl: (newConfig.customRtmpUrl !== undefined ? newConfig.customRtmpUrl : this.config.customRtmpUrl).trim(),
    };

    if (!this.config.serverUrl) {
      this.config.serverUrl = DEFAULT_DEV_CONFIG.serverUrl;
    }

    this.applyToClient();

    try {
      const module = NativeModules?.PdkDeviceModule;
      if (module && typeof module.saveDevConfig === 'function') {
        module.saveDevConfig(JSON.stringify(this.config));
      }
    } catch (e) {
      console.warn('[DevSettingsService] 持久化保存配置失败:', e);
    }
  }

  public resetDefaults(): DevConfig {
    this.saveConfig({ ...DEFAULT_DEV_CONFIG });
    return this.getConfig();
  }

  public getServerUrl(): string {
    return this.getConfig().serverUrl;
  }

  public getCustomRtmpUrl(): string {
    return this.getConfig().customRtmpUrl;
  }

  public isDirectRtmp(): boolean {
    const rtmp = this.getCustomRtmpUrl();
    return Boolean(rtmp && rtmp.trim().length > 0);
  }
}

export const devSettingsService = new DevSettingsService();
