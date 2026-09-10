import { NativeModules } from 'react-native';

export interface SavedAuthCredentials {
  phone: string;
  password?: string;
  rememberPassword: boolean;
  tokenName?: string;
  tokenValue?: string;
  authMode?: string;
  lastLoginTime?: number;
}

class AuthStorageService {
  public getSavedCredentials(): SavedAuthCredentials | null {
    try {
      const module = NativeModules?.PdkDeviceModule;
      if (module && typeof module.getAuthCredentialsSync === 'function') {
        const raw = module.getAuthCredentialsSync();
        if (raw && typeof raw === 'string' && raw.trim().length > 0) {
          return JSON.parse(raw);
        }
      }
    } catch (e) {
      console.warn('[AuthStorageService] 读取保存凭据失败:', e);
    }
    return null;
  }

  public saveCredentials(creds: SavedAuthCredentials): void {
    try {
      const module = NativeModules?.PdkDeviceModule;
      if (module && typeof module.saveAuthCredentials === 'function') {
        module.saveAuthCredentials(JSON.stringify(creds));
      }
    } catch (e) {
      console.warn('[AuthStorageService] 保存凭据失败:', e);
    }
  }

  public clearCredentials(): void {
    try {
      const module = NativeModules?.PdkDeviceModule;
      if (module && typeof module.clearAuthCredentials === 'function') {
        module.clearAuthCredentials();
      }
    } catch (e) {
      console.warn('[AuthStorageService] 清除凭据失败:', e);
    }
  }
}

export const authStorageService = new AuthStorageService();
