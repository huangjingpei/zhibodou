import { pdkClient, PdkClientError } from '../api/pdkClient';
import { PushTicketResult } from '../api/types';

export interface LiveStateListener {
  onStateChange: (isLive: boolean, sessionNo?: string) => void;
  onError: (error: string) => void;
}

/**
 * 智播推流服务编排层
 * 严格遵循安全红线与 40971 遗留活动会话自愈重试规范
 */
class LiveService {
  private activeSessionNo: string = '';
  private isStreaming: boolean = false;
  private listeners: Set<LiveStateListener> = new Set();

  public addListener(listener: LiveStateListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  public getIsStreaming(): boolean {
    return this.isStreaming;
  }

  public getActiveSessionNo(): string {
    return this.activeSessionNo;
  }

  /**
   * 开始直播：申请短效推流票据
   * 遇到 40971 冲突时自动阻断清理旧会话并重试
   */
  public async startLive(title: string = '智播移动端开播'): Promise<PushTicketResult> {
    let lastError: any = null;

    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        const ticket = await pdkClient.acquirePushTicket(title);
        this.activeSessionNo = ticket.streamSessionNo;
        this.isStreaming = true;
        this.notifyState(true, this.activeSessionNo);
        return ticket;
      } catch (err: any) {
        lastError = err;
        // 40971: 存在未释放的旧直播会话，执行自愈释放
        if (err instanceof PdkClientError && err.code === 40971) {
          console.warn(`[LiveService] 检测到遗留活动流 (40971)，正在执行自动清理 (第 ${attempt} 次重试)...`);
          await this.cleanLeftoverSessionsQuietly();
          await new Promise((resolve) => setTimeout(resolve, 500 * attempt));
          continue;
        }
        break;
      }
    }

    this.notifyError(lastError?.message || '开播申请失败');
    throw lastError;
  }

  /**
   * 停止直播
   */
  public async stopLive(): Promise<void> {
    const sessionToStop = this.activeSessionNo;
    this.isStreaming = false;
    this.activeSessionNo = '';
    this.notifyState(false);

    if (sessionToStop) {
      try {
        await pdkClient.stopStream(sessionToStop);
      } catch (err) {
        console.warn('[LiveService] 停止远端流会话异常 (可忽略):', err);
      }
    }
  }

  /**
   * 静默清理所有属于当前账号的旧活动会话
   */
  private async cleanLeftoverSessionsQuietly(): Promise<void> {
    try {
      const activeList = await pdkClient.getCurrentStreams();
      if (Array.isArray(activeList)) {
        for (const item of activeList) {
          if (item.streamSessionNo && item.status !== 'ENDED') {
            await pdkClient.stopStream(item.streamSessionNo).catch(() => {});
          }
        }
      }
    } catch {
      // 忽略查询失败
    }
  }

  private notifyState(isLive: boolean, sessionNo?: string): void {
    this.listeners.forEach((l) => {
      try {
        l.onStateChange(isLive, sessionNo);
      } catch {}
    });
  }

  private notifyError(msg: string): void {
    this.listeners.forEach((l) => {
      try {
        l.onError(msg);
      } catch {}
    });
  }
}

export const liveService = new LiveService();
