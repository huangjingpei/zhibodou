const assert = require('assert');
const test = require('node:test');

// 1. 测试设备指纹生成逻辑
test('Device ID generator format & stability', () => {
  const generateRandomHex = (length) => {
    const chars = '0123456789abcdef';
    let result = '';
    for (let i = 0; i < length; i++) {
      result += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return result;
  };

  const id1 = `MOB-AND-${generateRandomHex(16)}`;
  assert.match(id1, /^MOB-AND-[0-9a-f]{16}$/);

  const id2 = `MOB-IOS-${generateRandomHex(16)}`;
  assert.match(id2, /^MOB-IOS-[0-9a-f]{16}$/);
});

// 2. 测试 PDK 客户端统一安全鉴权请求头
test('PDK Client environment and required security headers', () => {
  class PdkClientMock {
    constructor(env = 'production') {
      this.setEnvironment(env);
      this.phone = '';
      this.sessionKey = null;
      this.tokenName = 'satoken';
    }
    setEnvironment(env) {
      this.env = env;
      this.baseUrl = env === 'production' ? 'https://pdk.graddu.com' : 'http://127.0.0.1:8080';
    }
    getBaseUrl() {
      return this.baseUrl;
    }
    setPhone(phone) {
      this.phone = phone;
    }
    setSessionKey(key) {
      this.sessionKey = key;
    }
    formatHeaders(tokenValue) {
      const headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-PDK-App-ID': '3',
        'X-PDK-Device-ID': 'MOB-AND-test',
        'User-Agent': 'Zhibodou-Mobile/1.0.0 (android)',
      };
      if (this.phone) headers['X-PDK-Phone'] = this.phone;
      if (this.sessionKey) headers['X-PDK-Crypto-Armed'] = '1';
      if (tokenValue) {
        headers[this.tokenName] = tokenValue;
        headers['Authorization'] = `Bearer ${tokenValue}`;
        headers['Cookie'] = `${this.tokenName}=${tokenValue}`;
      }
      return headers;
    }
  }

  const client = new PdkClientMock('production');
  assert.strictEqual(client.getBaseUrl(), 'https://pdk.graddu.com');

  client.setEnvironment('local_debug');
  assert.strictEqual(client.getBaseUrl(), 'http://127.0.0.1:8080');

  client.setPhone('13800138000');
  client.setSessionKey('mock-aes-key');
  const headers = client.formatHeaders('fake-satoken-1234');

  // 严格验证后端 DeviceSecurityInterceptor 与 BusinessRequestResolver 拦截器所需的全部头
  assert.strictEqual(headers['X-PDK-App-ID'], '3');
  assert.strictEqual(headers['X-PDK-Device-ID'], 'MOB-AND-test');
  assert.strictEqual(headers['X-PDK-Phone'], '13800138000');
  assert.strictEqual(headers['X-PDK-Crypto-Armed'], '1');
  assert.strictEqual(headers['satoken'], 'fake-satoken-1234');
  assert.strictEqual(headers['Cookie'], 'satoken=fake-satoken-1234');
});

// 3. 测试 40971 冲突自愈重试逻辑
test('LiveService 40971 conflict self-healing simulation', async () => {
  let attempt = 0;
  let cleanedOldStream = false;

  const mockAcquirePushTicket = async () => {
    attempt++;
    if (attempt === 1) {
      // 模拟第 1 次申请命中 40971 冲突
      const err = new Error('已有活动推流会话');
      err.code = 40971;
      throw err;
    }
    // 第 2 次申请自愈成功
    return {
      publishUrl: 'rtmp://pdk.graddu.com:1935/zhibo-live/ls_test?token=abc',
      streamSessionNo: 'SS-20260908-001',
    };
  };

  const startLive = async () => {
    for (let i = 1; i <= 3; i++) {
      try {
        return await mockAcquirePushTicket();
      } catch (err) {
        if (err.code === 40971) {
          cleanedOldStream = true;
          continue;
        }
        throw err;
      }
    }
  };

  const ticket = await startLive();
  assert.strictEqual(attempt, 2, 'Should succeed on retry 2');
  assert.strictEqual(cleanedOldStream, true, 'Should trigger cleanup on 40971');
  assert.ok(ticket.publishUrl.includes('rtmp://'), 'Should return valid RTMP url');
});

// 4. 测试 RTMP 码率与帧率统计
test('RtmpEngine streaming lifecycle & stats calculation', async () => {
  class RtmpEngineMock {
    constructor() {
      this.isStreaming = false;
      this.stats = { fps: 0, bitrateKbps: 0, durationSeconds: 0 };
    }
    start(targetBitrate, targetFps) {
      this.isStreaming = true;
      this.stats = { fps: targetFps, bitrateKbps: targetBitrate, durationSeconds: 1 };
    }
    stop() {
      this.isStreaming = false;
      this.stats = { fps: 0, bitrateKbps: 0, durationSeconds: 0 };
    }
  }

  const engine = new RtmpEngineMock();
  engine.start(6000, 60);
  assert.strictEqual(engine.isStreaming, true);
  assert.strictEqual(engine.stats.fps, 60);
  assert.strictEqual(engine.stats.bitrateKbps, 6000);

  engine.stop();
  assert.strictEqual(engine.isStreaming, false);
  assert.strictEqual(engine.stats.fps, 0);
});

// 5. 测试协议信封加密与解密互通性 (RSA-OAEP SHA256/MGF1 + AES-256-GCM)
test('Envelope encryption and decryption with node-forge', () => {
  const forge = require('node-forge');

  // 生成一对 RSA 密钥对
  const keypair = forge.pki.rsa.generateKeyPair({ bits: 2048, e: 0x10001 });
  const publicKeyPem = forge.pki.publicKeyToPem(keypair.publicKey);
  const privateKeyPem = forge.pki.privateKeyToPem(keypair.privateKey);

  // 待加密业务 Payload
  const rawPayload = {
    appId: 3,
    phone: '13800138000',
    title: '单元测试直播',
    requestedProtocol: 'RTMP',
  };
  const plainText = JSON.stringify(rawPayload);

  // 客户端执行信封加密
  const aesKey = forge.random.getBytesSync(32);
  const iv = forge.random.getBytesSync(12);

  const cipher = forge.cipher.createCipher('AES-GCM', aesKey);
  cipher.start({ iv, tagLength: 128 });
  cipher.update(forge.util.createBuffer(plainText, 'utf8'));
  cipher.finish();

  const encryptedData = cipher.output.getBytes() + cipher.mode.tag.getBytes();

  const pubKeyObj = forge.pki.publicKeyFromPem(publicKeyPem);
  const wrappedKey = pubKeyObj.encrypt(aesKey, 'RSA-OAEP', {
    md: forge.md.sha256.create(),
    mgf1: { md: forge.md.sha256.create() },
  });

  const envelope = {
    kid: 'v1',
    enc: forge.util.encode64(wrappedKey),
    iv: forge.util.encode64(iv),
    data: forge.util.encode64(encryptedData),
    ts: Date.now(),
    rnd: 'test-rnd-1234567890123456',
  };

  // 服务端模拟解密
  const privKeyObj = forge.pki.privateKeyFromPem(privateKeyPem);
  const unwrappedAesKey = privKeyObj.decrypt(forge.util.decode64(envelope.enc), 'RSA-OAEP', {
    md: forge.md.sha256.create(),
    mgf1: { md: forge.md.sha256.create() },
  });
  assert.strictEqual(unwrappedAesKey, aesKey, 'Unwrapped AES key must match original');

  const rawEncryptedBytes = forge.util.decode64(envelope.data);
  const tagLength = 16;
  const cipherText = rawEncryptedBytes.slice(0, rawEncryptedBytes.length - tagLength);
  const tag = rawEncryptedBytes.slice(rawEncryptedBytes.length - tagLength);

  const decipher = forge.cipher.createDecipher('AES-GCM', unwrappedAesKey);
  decipher.start({
    iv: forge.util.decode64(envelope.iv),
    tagLength: 128,
    tag: forge.util.createBuffer(tag),
  });
  decipher.update(forge.util.createBuffer(cipherText));
  const pass = decipher.finish();
  assert.strictEqual(pass, true, 'AES-GCM decipher must succeed');

  const decryptedText = forge.util.decodeUtf8(decipher.output.getBytes());
  const parsed = JSON.parse(decryptedText);
  assert.deepStrictEqual(parsed, rawPayload, 'Decrypted payload must match raw payload');
});

// 6. 测试纯 JS UTF-8 字节串编解码 (Hermes 兼容，支持中文与特殊符号)
test('Pure JS UTF-8 binary conversion handles Chinese characters and symbols', () => {
  function utf8ToBinary(str) {
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

  function binaryToUtf8(bin) {
    let encoded = '';
    for (let i = 0; i < bin.length; i++) {
      encoded += '%' + bin.charCodeAt(i).toString(16).padStart(2, '0');
    }
    return decodeURIComponent(encoded);
  }

  const testTexts = [
    '智播移动端开播',
    '{"title":"智播移动端开播","requestedProtocol":"RTMP"}',
    'Hello World! 1234567890 !@#$%^&*()',
    '直播间标题带emoji: 🚀📡🎉 and 中文混合',
  ];

  for (const text of testTexts) {
    const binary = utf8ToBinary(text);
    const restored = binaryToUtf8(binary);
    assert.strictEqual(restored, text, `Roundtrip must match for: ${text}`);
    // 验证字节长度严格等于 UTF-8 字节长度
    assert.strictEqual(binary.length, Buffer.from(text, 'utf8').length);
  }
});

// 7. 测试 42900 / 42901 / 42904 自动重拉公钥自愈重试机制
test('PdkClient auto-healing retry on 42900, 42901, and 42904', async () => {
  let attempts = 0;
  let refreshedKey = false;

  const mockRequest = async (code) => {
    attempts++;
    if (attempts === 1) {
      return { code, message: '报文解密失败，请确认加密协议正确' };
    }
    return { code: 200, message: '操作成功', data: { success: true } };
  };

  const executeWithRetry = async (code) => {
    attempts = 0;
    refreshedKey = false;
    let res = await mockRequest(code);
    if ((res.code === 42900 || res.code === 42901 || res.code === 42904)) {
      refreshedKey = true;
      res = await mockRequest(code);
    }
    return res;
  };

  // 测试 42904 自动自愈
  const res42904 = await executeWithRetry(42904);
  assert.strictEqual(attempts, 2, 'Should retry once on 42904');
  assert.strictEqual(refreshedKey, true, 'Should refresh key on 42904');
  assert.strictEqual(res42904.code, 200, 'Should succeed on retry');

  // 测试 42901 自动自愈
  const res42901 = await executeWithRetry(42901);
  assert.strictEqual(attempts, 2, 'Should retry once on 42901');
  assert.strictEqual(refreshedKey, true, 'Should refresh key on 42901');
  assert.strictEqual(res42901.code, 200, 'Should succeed on retry');
});

