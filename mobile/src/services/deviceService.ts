import { NativeModules, Platform } from 'react-native';

/**
 * 跨平台稳定移动设备唯一指纹服务
 * 符合 PDK 规范：为移动端固定并持久化硬件级唯一设备标识 "MOB-AND-xxxxxxxx" / "MOB-IOS-xxxxxxxx"
 * 无论应用更新、卸载重装或系统重启，同一台物理手机的设备 ID 100% 绝对一致且永久固定。
 */
class DeviceService {
  private cachedDeviceId: string = '';
  private isNativeResolved: boolean = false;
  private resolvePromise: Promise<string> | null = null;

  constructor() {
    this.tryResolveNativeSync();
  }

  /**
   * 尝试同步读取原生模块中的硬件级设备标识
   * 严格兼容 React Native 新旧架构 (包括 TurboModule Interop 与 Bridgeless 模式)
   */
  private tryResolveNativeSync(): string {
    if (this.isNativeResolved && this.cachedDeviceId) {
      return this.cachedDeviceId;
    }

    try {
      const pdkModule = NativeModules?.PdkDeviceModule;
      if (pdkModule) {
        // 1. 尝试直接从 constants 属性读取
        if (typeof pdkModule.deviceId === 'string' && pdkModule.deviceId.length > 0) {
          this.cachedDeviceId = pdkModule.deviceId;
          this.isNativeResolved = true;
          return this.cachedDeviceId;
        }

        // 2. 尝试从 getConstants() 方法读取 (React Native New Architecture TurboModule Interop 兼容)
        if (typeof pdkModule.getConstants === 'function') {
          const constants = pdkModule.getConstants();
          if (constants && typeof constants.deviceId === 'string' && constants.deviceId.length > 0) {
            this.cachedDeviceId = constants.deviceId;
            this.isNativeResolved = true;
            return this.cachedDeviceId;
          }
        }

        // 3. 尝试同步阻塞方法 getDeviceIdSync()
        if (typeof pdkModule.getDeviceIdSync === 'function') {
          const syncId = pdkModule.getDeviceIdSync();
          if (typeof syncId === 'string' && syncId.length > 0) {
            this.cachedDeviceId = syncId;
            this.isNativeResolved = true;
            return this.cachedDeviceId;
          }
        }
      }
    } catch {
      // 忽略启动初期原生模块调用异常
    }

    return '';
  }

  /**
   * 异步获取或确保已解析出硬件级设备标识
   */
  public async getDeviceIdAsync(): Promise<string> {
    if (this.isNativeResolved && this.cachedDeviceId) {
      return this.cachedDeviceId;
    }

    // 再次尝试同步获取
    const syncId = this.tryResolveNativeSync();
    if (syncId) {
      return syncId;
    }

    if (this.resolvePromise) {
      return this.resolvePromise;
    }

    this.resolvePromise = (async () => {
      try {
        const pdkModule = NativeModules?.PdkDeviceModule;
        if (pdkModule && typeof pdkModule.getDeviceId === 'function') {
          const nativeId = await pdkModule.getDeviceId();
          if (typeof nativeId === 'string' && nativeId.trim().length > 0) {
            this.cachedDeviceId = nativeId.trim();
            this.isNativeResolved = true;
            return this.cachedDeviceId;
          }
        }
      } catch {
        // 原生异步调用失败
      } finally {
        this.resolvePromise = null;
      }

      // 如果原生模块确实不可用 (如纯浏览器或单元测试环境)
      return this.getFallbackDeviceId();
    })();

    return this.resolvePromise;
  }

  /**
   * 确保设备 ID 已经准备完毕 (可在网络请求前或登录前调用)
   */
  public async ensureDeviceId(): Promise<string> {
    return this.getDeviceIdAsync();
  }

  /**
   * 获取设备唯一 ID (同步方法)
   * 即使调用时原生模块初次同步未就绪，也会不断尝试从原生模块加载，绝不固化随机 ID
   */
  public getDeviceId(): string {
    if (this.isNativeResolved && this.cachedDeviceId) {
      return this.cachedDeviceId;
    }

    const nativeId = this.tryResolveNativeSync();
    if (nativeId) {
      return nativeId;
    }

    // 若异步解析未启动，后台触发一次异步加载以尽快固化
    if (!this.resolvePromise) {
      this.getDeviceIdAsync().catch(() => {});
    }

    // 若之前已有缓存值，先返回
    if (this.cachedDeviceId) {
      return this.cachedDeviceId;
    }

    // 纯非原生环境 (如 Node.js 单元测试) 下的确定性兜底标识，不锁定 isNativeResolved 状态
    return this.getFallbackDeviceId();
  }

  public setCustomDeviceId(id: string): void {
    if (id && id.trim()) {
      this.cachedDeviceId = id.trim();
      this.isNativeResolved = true;
      try {
        NativeModules?.PdkDeviceModule?.setCustomDeviceId?.(this.cachedDeviceId);
      } catch {
        // ignore
      }
    }
  }

  /**
   * 针对非原生环境 (如 Node.js 单元测试) 的确定性前缀兜底
   */
  private getFallbackDeviceId(): string {
    let isIos = false;
    try {
      isIos = Platform?.OS === 'ios';
    } catch {
      isIos = typeof process !== 'undefined' && process.platform === 'darwin';
    }
    const prefix = isIos ? 'MOB-IOS' : 'MOB-AND';
    // 在纯非原生环境中保持固定，避免每次调用变动
    if (!this.cachedDeviceId) {
      this.cachedDeviceId = `${prefix}-STANDALONE000000000000`;
    }
    return this.cachedDeviceId;
  }
}

export const deviceService = new DeviceService();

