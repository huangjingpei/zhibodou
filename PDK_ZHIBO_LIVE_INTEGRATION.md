# 智播豆客户端 PDK ZHIBO_LIVE 接入说明

本文记录当前客户端与 PDK 后端 `appId=3 / bizCode=ZHIBO_LIVE` 的实际接入方式。

## 1. 运行配置

默认配置来自环境变量：

```powershell
$env:PDK_BASE_URL = "http://127.0.0.1:8080"
$env:PDK_APP_ID = "3"
$env:PDK_BIZ_CODE = "ZHIBO_LIVE"
```

生产环境建议同时配置：

```powershell
$env:PDK_BASE_URL = "https://pdk.graddu.com"
$env:PDK_REQUIRE_HTTPS = "true"
$env:PDK_VERIFY_TLS = "true"
$env:PDK_PUBLIC_KEY_PIN = "<后端公钥指纹>"
```

## 2. 启动顺序

1. 程序启动先执行客户端升级检查，使用 `config/client-update.json`。
2. 显示登录窗口，调用 `pdk.auth_service.authenticate()`。
3. 认证顺序固定为：
   `fetch_public_config -> business_info -> login -> verify_session -> profile -> device_license_current`。
4. 只有所有校验通过后才进入主窗口。
5. 主窗口每 60 秒低频调用 `verify_current_session()`，关键操作前也会重新校验。

## 3. 登录和设备激活

ZHIBO_LIVE 是 `DEVICE_LICENSE` 授权模型：

- 已绑定电脑：登录页输入手机号和密码即可。
- 新电脑：普通登录会收到 `40380`，客户端自动切到“激活”页。
- 激活页输入手机号、密码、卡密后再次登录，后端把该卡密绑定到当前设备。
- 同一手机号可拥有多张卡密，多台电脑分别使用自己的卡密登录。
- 一张卡密不能同时绑定两台电脑；需要换机时先在后台或原设备解绑。

本地保存的手机号、密码、卡密只用于下次回填，文件位于用户数据目录，不进入版本库。

## 4. 直播媒体发现

登录前业务发现会返回 `liveMedia`，客户端通过 `PdkClient.live_media_info()` 或认证快照读取：

```python
media = result.live_media
media_server = media.get("mediaServerAddress")
```

该地址只用于显示和网络预检。客户端不能用它自行拼接最终 RTMP URL。

## 5. 开始推流

点击“开始直播推流”时：

1. UI 调用 `MainWin.run_authorized()` 再次校验会话、许可证、到期时间和次数。
2. `sessions.host.HostStream.start_streaming()` 调用 `pdk.live_service.acquire_push_ticket()`。
3. 后端返回完整短效 `publishUrl` 和 `streamSessionNo`。
4. 客户端把 `publishUrl` 直接交给 PyAV 或 ffmpeg。
5. UI 和日志只显示 host、会话号和状态，不显示完整 `publishUrl`。

后端托管推流时，断线后不复用旧票据自动重连；用户重新点击开始直播会申请新票据。

## 6. 停止推流和退出

- 停止直播会调用 `live_stream_stop()`，服务端将会话置为结束。
- 推流启动失败会尽力释放刚签发的服务端会话。
- 点击退出登录会先释放音视频资源，再调用服务端 logout。
- 服务端 logout 失败也会清理本地 Token 和 HTTP Session，不会卡住用户退出。

## 7. 关键文件

```text
pdk/pdk_client.py        PDK 原始协议客户端
pdk/auth_service.py      UI 与业务层使用的认证编排层
pdk/live_service.py      推流票据申请与会话释放
ui/login_window.py       登录/激活窗口
ui/panels/auth.py        主播页账户与许可证展示
ui/panels/host.py        主播页开始/停止推流交互
sessions/host.py         采集、处理、推流业务编排
streaming/factory.py     PyAV/ffmpeg 推流后端选择
```

## 8. 常见错误

| 错误码 | 客户端动作 |
| --- | --- |
| `40380` | 切到激活页，要求输入卡密 |
| `40381` | 许可证到期，仅保留查询、退出和解绑 |
| `40383` | 卡密已绑定其他设备，先解绑 |
| `40384` | 许可证暂停或作废，联系管理员 |
| `40971` | 有遗留直播会话，客户端会先停止旧会话再重试 |
| `50372` | 没有可用直播媒体节点，检查后台直播中心 |

## 9. 本地验证

```powershell
python -m unittest tests.test_pdk_auth_service tests.test_login_window
python -m compileall -q .
```

真实联调需先启动 PDK 后端和 MediaMTX，并准备一个 `ZHIBO_LIVE` 用户、有效设备许可证和未绑定卡密。
