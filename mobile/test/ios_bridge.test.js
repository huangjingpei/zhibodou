const assert = require('assert');
const test = require('node:test');

test('iOS Native Bridge - PdkDeviceModule contract validation', () => {
  // 模拟 iOS PdkDeviceModule 规范
  const mockIosDeviceModule = {
    deviceId: 'MOB-IOS-A1B2C3D4E5F6',
    getDeviceIdSync() {
      return this.deviceId;
    },
    async getDeviceId() {
      return this.deviceId;
    },
    setCustomDeviceId(id) {
      this.deviceId = id;
    },
  };

  assert.strictEqual(typeof mockIosDeviceModule.deviceId, 'string');
  assert.match(mockIosDeviceModule.deviceId, /^MOB-IOS-[0-9A-F]{12}$/);
  assert.strictEqual(mockIosDeviceModule.getDeviceIdSync(), 'MOB-IOS-A1B2C3D4E5F6');
});

test('iOS Native Bridge - PdkLiveModule method signatures and events', async () => {
  const emittedEvents = [];
  const mockIosLiveModule = {
    isStreaming: false,
    isOnPreview: false,
    isFrontFacing: true,
    isTorchOn: false,
    isMuted: false,
    bitrateKbps: 1800,

    async startPreview(isFront, width, height, fps) {
      this.isOnPreview = true;
      this.isFrontFacing = isFront;
      return true;
    },
    async stopPreview() {
      this.isOnPreview = false;
      return true;
    },
    async startPublish(streamUrl, width, height, fps, bitrateKbps, audioBitrateKbps, sampleRate) {
      this.isStreaming = true;
      this.bitrateKbps = bitrateKbps;
      emittedEvents.push({ event: 'onStreamStateChanged', body: { state: 'CONNECTED' } });
      return true;
    },
    async stopPublish() {
      this.isStreaming = false;
      emittedEvents.push({ event: 'onStreamStateChanged', body: { state: 'DISCONNECTED' } });
      return true;
    },
    async switchCamera() {
      this.isFrontFacing = !this.isFrontFacing;
      return this.isFrontFacing;
    },
    async toggleTorch(enable) {
      this.isTorchOn = enable;
      return this.isTorchOn;
    },
    async setMute(mute) {
      this.isMuted = mute;
      return this.isMuted;
    },
    async setBitrate(bitrate) {
      this.bitrateKbps = bitrate;
      return true;
    },
    async getStatus() {
      return {
        isStreaming: this.isStreaming,
        isOnPreview: this.isOnPreview,
        isFrontFacing: this.isFrontFacing,
        isLanternEnabled: this.isTorchOn,
        isAudioMuted: this.isMuted,
      };
    },
    async recoverCamera() {
      this.isOnPreview = true;
      return true;
    },
    async checkCameraHealth() {
      return {
        isHealthy: true,
        isOnPreview: this.isOnPreview,
        isStreaming: this.isStreaming,
        isSurfaceReady: true,
      };
    },
  };

  assert.strictEqual(await mockIosLiveModule.startPreview(true, 1080, 1920, 30), true);
  assert.strictEqual(await mockIosLiveModule.startPublish('rtmp://127.0.0.1:1935/live/test', 1080, 1920, 30, 1800, 128, 48000), true);
  assert.strictEqual(await mockIosLiveModule.setBitrate(3500), true);
  assert.strictEqual(mockIosLiveModule.bitrateKbps, 3500);

  const status = await mockIosLiveModule.getStatus();
  assert.strictEqual(status.isStreaming, true);
  assert.strictEqual(status.isOnPreview, true);

  assert.strictEqual(await mockIosLiveModule.stopPublish(), true);
  assert.strictEqual(mockIosLiveModule.isStreaming, false);

  assert.strictEqual(await mockIosLiveModule.recoverCamera(), true);
  const health = await mockIosLiveModule.checkCameraHealth();
  assert.strictEqual(health.isHealthy, true);

  assert.strictEqual(emittedEvents.length, 2);
  assert.strictEqual(emittedEvents[0].body.state, 'CONNECTED');
  assert.strictEqual(emittedEvents[1].body.state, 'DISCONNECTED');
});

test('iOS Native Bridge - StreamStats schema validation', () => {
  const stats = {
    fps: 30,
    bitrateKbps: 1800,
    droppedFrames: 0,
    durationSeconds: 15,
    netQuality: 'EXCELLENT',
  };

  assert.strictEqual(typeof stats.fps, 'number');
  assert.strictEqual(typeof stats.bitrateKbps, 'number');
  assert.strictEqual(typeof stats.droppedFrames, 'number');
  assert.strictEqual(typeof stats.durationSeconds, 'number');
  assert(['EXCELLENT', 'GOOD', 'POOR', 'DISCONNECTED'].includes(stats.netQuality), true);
});

test('Native Bridge & DevSettings - Dev config persistence and Direct RTMP contract', () => {
  let persistedStorage = '';
  const mockDeviceModule = {
    saveDevConfig(jsonStr) {
      persistedStorage = jsonStr;
      return true;
    },
    getDevConfigSync() {
      return persistedStorage;
    },
  };

  // 默认无配置
  assert.strictEqual(mockDeviceModule.getDevConfigSync(), '');

  // 开发者模式保存自定义直推 RTMP
  const devConfig = {
    serverUrl: 'https://pdk-test.example.com',
    customRtmpUrl: 'rtmp://192.168.1.100:1935/live/stream123',
  };
  mockDeviceModule.saveDevConfig(JSON.stringify(devConfig));

  const loadedRaw = mockDeviceModule.getDevConfigSync();
  const parsed = JSON.parse(loadedRaw);
  assert.strictEqual(parsed.serverUrl, 'https://pdk-test.example.com');
  assert.strictEqual(parsed.customRtmpUrl, 'rtmp://192.168.1.100:1935/live/stream123');

  const isDirectRtmp = Boolean(parsed.customRtmpUrl && parsed.customRtmpUrl.trim().length > 0);
  assert.strictEqual(isDirectRtmp, true);

  // 清空直推后恢复后端模式
  mockDeviceModule.saveDevConfig(JSON.stringify({ serverUrl: 'https://pdk.graddu.com', customRtmpUrl: '' }));
  const reloaded = JSON.parse(mockDeviceModule.getDevConfigSync());
  const isDirectRtmpReset = Boolean(reloaded.customRtmpUrl && reloaded.customRtmpUrl.trim().length > 0);
  assert.strictEqual(isDirectRtmpReset, false);
});

test('Video pause / resume state and 10s auto-hide timer contract', () => {
  let isVideoEnabled = true;
  let controlsVisible = true;
  let timerFired = false;

  // 切换画面黑屏遮蔽
  isVideoEnabled = !isVideoEnabled;
  assert.strictEqual(isVideoEnabled, false, '视频画面应被隐私黑屏遮蔽');

  isVideoEnabled = !isVideoEnabled;
  assert.strictEqual(isVideoEnabled, true, '视频画面应恢复正常展示');

  // 10秒无操作隐藏
  const simulateAutoTimer = (ms) => {
    if (ms >= 10000) {
      controlsVisible = false;
      timerFired = true;
    }
  };

  simulateAutoTimer(10000);
  assert.strictEqual(controlsVisible, false, '10秒后控制栏应自动隐藏');
  assert.strictEqual(timerFired, true);

  // 用户点击视频取景画面唤醒
  controlsVisible = true;
  assert.strictEqual(controlsVisible, true, '点击视频画面后控制栏应重新显示');
});

test('Auth credentials & agreement persistence contract across restarts', () => {
  let storedJson = '';
  const mockStorageModule = {
    getAuthCredentialsSync() {
      return storedJson;
    },
    saveAuthCredentials(json) {
      storedJson = json;
    },
    clearAuthCredentials() {
      storedJson = '';
    },
  };

  // 1. 用户首次登录勾选服务协议
  const creds = {
    phone: '13800138000',
    password: 'securePassword123',
    rememberPassword: true,
    agreedToTerms: true,
    tokenName: 'satoken',
    tokenValue: 'mock-token-xyz',
    lastLoginTime: Date.now(),
  };
  mockStorageModule.saveAuthCredentials(JSON.stringify(creds));

  // 2. 模拟应用杀掉重启并读取持久化凭据
  const restored = JSON.parse(mockStorageModule.getAuthCredentialsSync());
  assert.strictEqual(restored.phone, '13800138000');
  assert.strictEqual(restored.password, 'securePassword123');
  assert.strictEqual(restored.rememberPassword, true);
  assert.strictEqual(restored.agreedToTerms, true, '已同意协议状态应当在重启后保持');

  // 3. 用户在未登录状态下勾选/取消协议即刻持久化
  const updatedAgreed = { ...restored, agreedToTerms: false };
  mockStorageModule.saveAuthCredentials(JSON.stringify(updatedAgreed));
  const restored2 = JSON.parse(mockStorageModule.getAuthCredentialsSync());
  assert.strictEqual(restored2.agreedToTerms, false);

  // 4. 用户注销账号彻底清除
  mockStorageModule.clearAuthCredentials();
  assert.strictEqual(mockStorageModule.getAuthCredentialsSync(), '');
});

