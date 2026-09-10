import { VideoAudioSettings } from '../api/types';

export interface StreamStats {
  fps: number;
  bitrateKbps: number;
  droppedFrames: number;
  durationSeconds: number;
  netQuality: 'EXCELLENT' | 'GOOD' | 'POOR' | 'DISCONNECTED';
}

export type StreamStatsCallback = (stats: StreamStats) => void;
export type StreamStateCallback = (state: string, error?: string) => void;

let PdkLive: any = null;
let liveEmitter: any = null;

try {
  const RN = require('react-native');
  if (RN && RN.NativeModules) {
    PdkLive = RN.NativeModules.PdkLiveModule;
    if (PdkLive && RN.NativeEventEmitter) {
      liveEmitter = new RN.NativeEventEmitter(PdkLive);
    }
  }
} catch {
  // Node / 单元测试无原生环境降级运行
}

/**
 * 跨平台 RTMP 采集与推流适配引擎
 * 直通 Android 原生 MediaCodec (H.264 / AAC) 与 RTMP 原生推流模块
 */
class RtmpEngine {
  private isStreaming: boolean = false;
  private fallbackTimer: any = null;
  private durationSeconds: number = 0;
  private currentStats: StreamStats = {
    fps: 0,
    bitrateKbps: 0,
    droppedFrames: 0,
    durationSeconds: 0,
    netQuality: 'DISCONNECTED',
  };
  private statsListeners: Set<StreamStatsCallback> = new Set();
  private stateListeners: Set<StreamStateCallback> = new Set();

  constructor() {
    this.initNativeListeners();
  }

  private initNativeListeners(): void {
    if (liveEmitter) {
      try {
        liveEmitter.addListener('onStreamStats', (stats: StreamStats) => {
          this.currentStats = {
            fps: stats.fps || 0,
            bitrateKbps: stats.bitrateKbps || 0,
            droppedFrames: stats.droppedFrames || 0,
            durationSeconds: stats.durationSeconds || 0,
            netQuality: stats.netQuality || 'GOOD',
          };
          this.emitStats();
        });

        liveEmitter.addListener('onStreamStateChanged', (event: any) => {
          const state = event?.state || '';
          const error = event?.error;
          if (state === 'CONNECTED') {
            this.isStreaming = true;
          } else if (state === 'DISCONNECTED' || state === 'FAILED') {
            this.isStreaming = false;
          }
          this.emitState(state, error);
        });
      } catch (err) {
        console.warn('[RtmpEngine] 原生事件监听绑定失败 (忽略):', err);
      }
    }
  }

  public subscribeStats(callback: StreamStatsCallback): () => void {
    this.statsListeners.add(callback);
    callback(this.currentStats);
    return () => this.statsListeners.delete(callback);
  }

  public subscribeState(callback: StreamStateCallback): () => void {
    this.stateListeners.add(callback);
    return () => this.stateListeners.delete(callback);
  }

  /**
   * 启动真实摄像头画面预览
   */
  public async startPreview(
    isFront: boolean = true,
    width: number = 1080,
    height: number = 1920,
    fps: number = 30
  ): Promise<boolean> {
    if (PdkLive && typeof PdkLive.startPreview === 'function') {
      try {
        return await PdkLive.startPreview(isFront, width, height, fps);
      } catch (e) {
        console.warn('[RtmpEngine] 原生 startPreview 异常:', e);
        return false;
      }
    }
    return true;
  }

  /**
   * 停止摄像头画面预览
   */
  public async stopPreview(): Promise<boolean> {
    if (PdkLive && typeof PdkLive.stopPreview === 'function') {
      try {
        return await PdkLive.stopPreview();
      } catch (e) {
        console.warn('[RtmpEngine] 原生 stopPreview 异常:', e);
        return false;
      }
    }
    return true;
  }

  /**
   * 启动推流管线 (MediaCodec 硬件编码 + RTMP 网络传输)
   */
  public async startPublish(publishUrl: string, settings: VideoAudioSettings): Promise<void> {
    this.isStreaming = true;
    this.durationSeconds = 0;
    this.currentStats = {
      fps: settings.fps,
      bitrateKbps: settings.bitrateKbps,
      droppedFrames: 0,
      durationSeconds: 0,
      netQuality: 'EXCELLENT',
    };
    this.emitStats();

    if (PdkLive && typeof PdkLive.startPublish === 'function') {
      try {
        const [w, h] = [settings.resolution.width, settings.resolution.height];
        await PdkLive.startPublish(
          publishUrl,
          w,
          h,
          settings.fps,
          settings.bitrateKbps,
          settings.audioBitrateKbps,
          settings.audioSampleRate
        );
        return;
      } catch (err) {
        console.error('[RtmpEngine] 原生 startPublish 失败:', err);
        this.isStreaming = false;
        throw err;
      }
    }

    // 回退模拟运行 (单元测试/模拟器)
    if (this.fallbackTimer) clearInterval(this.fallbackTimer);
    this.fallbackTimer = setInterval(() => {
      this.durationSeconds += 1;
      const jitter = Math.floor(Math.random() * 200 - 100);
      const actualBitrate = Math.max(800, settings.bitrateKbps + jitter);
      const actualFps = Math.max(settings.fps - 1, settings.fps);

      this.currentStats = {
        fps: actualFps,
        bitrateKbps: actualBitrate,
        droppedFrames: 0,
        durationSeconds: this.durationSeconds,
        netQuality: 'EXCELLENT',
      };
      this.emitStats();
    }, 1000);
  }

  /**
   * 停止推流管线
   */
  public async stopPublish(): Promise<void> {
    this.isStreaming = false;
    if (this.fallbackTimer) {
      clearInterval(this.fallbackTimer);
      this.fallbackTimer = null;
    }
    this.durationSeconds = 0;
    this.currentStats = {
      fps: 0,
      bitrateKbps: 0,
      droppedFrames: 0,
      durationSeconds: 0,
      netQuality: 'DISCONNECTED',
    };
    this.emitStats();

    if (PdkLive && typeof PdkLive.stopPublish === 'function') {
      try {
        await PdkLive.stopPublish();
      } catch (err) {
        console.warn('[RtmpEngine] 原生 stopPublish 异常 (忽略):', err);
      }
    }
  }

  /**
   * 翻转摄像头 (前摄 <-> 后摄)
   */
  public async switchCamera(): Promise<boolean> {
    if (PdkLive && typeof PdkLive.switchCamera === 'function') {
      try {
        return await PdkLive.switchCamera();
      } catch (e) {
        console.warn('[RtmpEngine] 原生 switchCamera 异常:', e);
      }
    }
    return false;
  }

  /**
   * 开启或关闭补光闪光灯 (仅后置镜头)
   */
  public async toggleTorch(enable: boolean): Promise<boolean> {
    if (PdkLive && typeof PdkLive.toggleTorch === 'function') {
      try {
        return await PdkLive.toggleTorch(enable);
      } catch (e) {
        console.warn('[RtmpEngine] 原生 toggleTorch 异常:', e);
      }
    }
    return false;
  }

  /**
   * 切换麦克风静音
   */
  public async setMute(mute: boolean): Promise<boolean> {
    if (PdkLive && typeof PdkLive.setMute === 'function') {
      try {
        return await PdkLive.setMute(mute);
      } catch (e) {
        console.warn('[RtmpEngine] 原生 setMute 异常:', e);
      }
    }
    return false;
  }

  /**
   * 动态调节推流码率 (On-the-fly)
   */
  public async setBitrate(bitrateKbps: number): Promise<boolean> {
    if (PdkLive && typeof PdkLive.setBitrate === 'function') {
      try {
        return await PdkLive.setBitrate(bitrateKbps);
      } catch (e) {
        console.warn('[RtmpEngine] 原生 setBitrate 异常:', e);
      }
    }
    return false;
  }

  /**
   * 强力自愈重启摄像头与取景管线
   * 彻底解决黑屏死锁或 HAL 掉线
   */
  public async recoverCamera(): Promise<boolean> {
    if (PdkLive && typeof PdkLive.recoverCamera === 'function') {
      try {
        return await PdkLive.recoverCamera();
      } catch (e) {
        console.warn('[RtmpEngine] recoverCamera 异常:', e);
        return false;
      }
    }
    return true;
  }

  /**
   * 检查底层相机与 Surface 健康状态
   */
  public async checkCameraHealth(): Promise<{
    isHealthy: boolean;
    isOnPreview: boolean;
    isStreaming: boolean;
    isSurfaceReady: boolean;
  }> {
    if (PdkLive && typeof PdkLive.checkCameraHealth === 'function') {
      try {
        return await PdkLive.checkCameraHealth();
      } catch (e) {
        console.warn('[RtmpEngine] checkCameraHealth 异常:', e);
      }
    }
    return { isHealthy: true, isOnPreview: true, isStreaming: this.isStreaming, isSurfaceReady: true };
  }

  private emitStats(): void {
    this.statsListeners.forEach((fn) => {
      try {
        fn(this.currentStats);
      } catch {}
    });
  }

  private emitState(state: string, error?: string): void {
    this.stateListeners.forEach((fn) => {
      try {
        fn(state, error);
      } catch {}
    });
  }
}

export const rtmpEngine = new RtmpEngine();
