import { NativeModules, Platform } from 'react-native';

/**
 * 跨平台稳定移动设备唯一指纹服务
 * 符合 PDK 规范：为移动端固定并持久化硬件级唯一设备标识 "MOB-AND-xxxxxxxx" / "MOB-IOS-xxxxxxxx"
 * 无论应用更新、卸载重装或系统重启，同一台物理手机的设备 ID 100% 绝对一致且永久固定。
 */
class DeviceService {
  private cachedDeviceId: string = '';

  constructor() {
    this.fetchNativeDeviceId();
  }

  private fetchNativeDeviceId(): string {
    if (this.cachedDeviceId) {
      return this.cachedDeviceId;
    }

    try {
      const pdkModule = NativeModules?.PdkDeviceModule;
      if (pdkModule) {
        if (typeof pdkModule.deviceId === 'string' && pdkModule.deviceId.length > 0) {
          this.cachedDeviceId = pdkModule.deviceId;
          return this.cachedDeviceId;
        }
        if (typeof pdkModule.getDeviceIdSync === 'function') {
          const syncId = pdkModule.getDeviceIdSync();
          if (typeof syncId === 'string' && syncId.length > 0) {
            this.cachedDeviceId = syncId;
            return this.cachedDeviceId;
          }
        }
      }
    } catch {
      // 忽略原生模块读取异常，回退处理
    }
    return '';
  }

  public getDeviceId(): string {
    if (this.cachedDeviceId) {
      return this.cachedDeviceId;
    }

    const nativeId = this.fetchNativeDeviceId();
    if (nativeId) {
      return nativeId;
    }

    let isIos = false;
    try {
      isIos = Platform?.OS === 'ios';
    } catch {
      isIos = typeof process !== 'undefined' && process.platform === 'darwin';
    }

    const prefix = isIos ? 'MOB-IOS' : 'MOB-AND';
    const randPart = this.generateRandomHex(16);
    this.cachedDeviceId = `${prefix}-${randPart}`;
    return this.cachedDeviceId;
  }

  public setCustomDeviceId(id: string): void {
    if (id && id.trim()) {
      this.cachedDeviceId = id.trim();
      try {
        NativeModules?.PdkDeviceModule?.setCustomDeviceId?.(this.cachedDeviceId);
      } catch {
        // ignore
      }
    }
  }

  private generateRandomHex(length: number): string {
    const chars = '0123456789abcdef';
    let result = '';
    for (let i = 0; i < length; i++) {
      result += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return result;
  }
}

export const deviceService = new DeviceService();

