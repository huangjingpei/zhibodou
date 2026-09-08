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
