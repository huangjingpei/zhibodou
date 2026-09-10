import { NativeModules } from 'react-native';

export interface SavedAuthCredentials {
  phone: string;
  password?: string;
  rememberPassword?: boolean;
  agreedToTerms?: boolean;
  tokenName?: string;
  tokenValue?: string;
  authMode?: string;
  lastLoginTime?: number;
}

class AuthStorageService {
  private cachedCreds: SavedAuthCredentials | null = null;
  private isLoaded: boolean = false;

  constructor() {
    this.tryLoadSync();
  }

  private tryLoadSync(): void {
    if (this.isLoaded && this.cachedCreds) return;
    try {
      const module = NativeModules?.PdkDeviceModule;
      if (module && typeof module.getAuthCredentialsSync === 'function') {
        const raw = module.getAuthCredentialsSync();
        if (raw && typeof raw === 'string' && raw.trim().length > 0) {
          this.cachedCreds = JSON.parse(raw);
          this.isLoaded = true;
          console.log('[AuthStorageService] 同步读取本地凭据成功, 账号:', this.cachedCreds?.phone, '记住密码:', this.cachedCreds?.rememberPassword);
        }
      }
    } catch (e) {
      console.warn('[AuthStorageService] 同步读取凭据异常:', e);
    }
  }

  public getSavedCredentials(): SavedAuthCredentials | null {
    this.tryLoadSync();
    return this.cachedCreds;
  }

  public async getSavedCredentialsAsync(): Promise<SavedAuthCredentials | null> {
    if (this.cachedCreds) {
      return this.cachedCreds;
    }
    this.tryLoadSync();
    if (this.cachedCreds) {
      return this.cachedCreds;
    }

    try {
      const module = NativeModules?.PdkDeviceModule;
      if (module && typeof module.getAuthCredentials === 'function') {
        const raw = await module.getAuthCredentials();
        if (raw && typeof raw === 'string' && raw.trim().length > 0) {
          this.cachedCreds = JSON.parse(raw);
          this.isLoaded = true;
          console.log('[AuthStorageService] 异步读取本地凭据成功, 账号:', this.cachedCreds?.phone, '记住密码:', this.cachedCreds?.rememberPassword);
          return this.cachedCreds;
        }
      }
    } catch (e) {
      console.warn('[AuthStorageService] 异步读取凭据异常:', e);
    }

    return null;
  }

  public saveCredentials(creds: SavedAuthCredentials): void {
    this.cachedCreds = { ...creds };
    this.isLoaded = true;
    try {
      const module = NativeModules?.PdkDeviceModule;
      const json = JSON.stringify(creds);
      if (module && typeof module.saveAuthCredentials === 'function') {
        module.saveAuthCredentials(json);
        console.log(
          `[AuthStorageService] 已持久化凭据: phone=${creds.phone}, remember=${creds.rememberPassword}, hasPassword=${Boolean(creds.password)}`
        );
      }
    } catch (e) {
      console.warn('[AuthStorageService] 保存凭据失败:', e);
    }
  }

  public clearCredentials(): void {
    this.cachedCreds = null;
    this.isLoaded = true;
    try {
      const module = NativeModules?.PdkDeviceModule;
      if (module && typeof module.clearAuthCredentials === 'function') {
        module.clearAuthCredentials();
        console.log('[AuthStorageService] 已彻底清除保存的凭据');
      }
    } catch (e) {
      console.warn('[AuthStorageService] 清除凭据失败:', e);
    }
  }
}

export const authStorageService = new AuthStorageService();
