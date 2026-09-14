# PDK Windows 客户端升级方案 — 原理与接入指南

> 适用对象：需要接入 PDK 客户端自动升级的 Windows 桌面客户端（PyInstaller 发布形态）。
> 参考实现：智播豆客户端（`E:\zhibodou`，`client_update/` 包 + `build_exe.py` + `config/client-update.json`）。
> 服务端：PDK 后端（本地 `http://127.0.0.1:8080`，生产 `https://pdk.graddu.com`）。

---

## 1. 方案总览

### 1.1 角色划分

| 角色 | 职责 | 关键文件 |
|---|---|---|
| 主程序（宿主客户端） | 启动期检查更新、弹窗、下载、拉起升级器后退出 | `main.py` 调 `client_update/qt_flow.py` |
| 升级领域服务 | 检查、策略验签、断点下载、构件验签 | `client_update/manager.py`、`api.py` |
| 独立升级器 | 二次验签、替换文件、健康检查、回滚 | `client_update/updater.py`（独立 EXE） |
| 服务端 | 策略判定、签名、构件分发、事件归集 | PDK 后端 `/api/v1/client/updates/*` |
| 打包器 | 生成带 `update-manifest.json` 的合规升级包 | `E:\pdk\scripts\build_update_package.py` |

### 1.2 一次完整升级的时序

```
主程序启动
  │  ①GET /api/v1/client/updates/check（带 X-PDK-App-ID / X-PDK-Device-ID）
  │     ← 策略决策(hasUpdate/updatePolicy/targetVersion) + Ed25519 策略签名 + 已签名构件
  │  ②验策略签名 → 缓存 trusted-policy.json → 上报 OFFERED
  │  ③弹窗（REQUIRED 不可跳过）→ 用户确认
  │  ④下载 artifact（Range 断点续传）→ SHA-256 → Ed25519 构件验签
  │  ⑤写 pending-update.json → 复制 zhibodou_updater.exe 到缓存目录
  │  ⑥Popen 启动升级器（带 --parent-pid 等 17 个参数）→ 上报 INSTALL_STARTED
  │  ⑦主程序退出
  ▼
独立升级器（onefile EXE，bootloader + python 双进程）
  │  ⑧验包（大小/SHA-256/Ed25519 二次验签）
  │  ⑨清理父进程树（排除自己/子孙/祖先链）→ 等待主程序退出（≤90s）
  │  ⑩安全解压到 .staging（清单校验 + 路径安全 + 8GiB 上限）
  │  ⑪版本替换：目录级原子替换 → 失败则逐文件就地同步（自动降级）
  │  ⑫启动新版入口（注入 PDK_UPDATE_HEALTH_FILE/NONCE）
  │  ⑬轮询健康文件（nonce+version 匹配，≤45s）→ 通过：
  │       上报 INSTALL_SUCCEEDED、删备份、删 pending-update.json
  │     超时/异常 → 自动回滚旧版本并拉起旧版 → 上报 INSTALL_FAILED
  ▼
新版程序启动 → mark_update_healthy(version) 写健康标记 → 升级闭环
```

### 1.3 为什么升级器必须是独立进程

- 主程序退出后才能替换自身文件，**替换动作必须由第三个进程执行**；
- 升级器复制到缓存目录再运行（`pdk-updater-<ver>-<rand>.exe`），避免它自己锁住安装目录；
- 升级器无控制台（`--windowed`），**可观测性完全依赖文件日志**。

---

## 2. 安全模型（必须完整保留）

1. **双 Ed25519 验签**，公钥内置客户端 `client-update.json`：
   - 策略签名（`policySignature`）：canonical 串 `PDK-POLICY-V1`（见 `security.policy_canonical`），
     覆盖 protocolVersion/appId/channel/platform/arch/policyRevision/updatePolicy/版本区间/签发与过期时间；
   - 构件签名（`artifact.signature`）：canonical 串 `PDK-ARTIFACT-V1`，覆盖
     appId/targetVersion/platform/arch/packageType/fileSize/sha256。
   - **任何一处签名失败立即中止**；主程序验一次，升级器安装前再验一次（防下载后文件被换）。
2. **作用域校验**：响应的 appId/channel/platform/arch 必须与本地配置完全一致（`_validate_response_scope`）。
3. **强制更新离线兜底**：验签通过且在有效期内的 REQUIRED 策略会缓存到
   `trusted-policy.json`；断网且仍在 `policyExpiresAt + offlineGraceHours` 宽限期内时**拒绝启动**，
   防止绕过强制升级；同时检测本机时间回拨。
4. **升级包自校验**：服务端打包器生成的 `update-manifest.json` 在安装前被逐项核对
   （appId/version/platform/arch/entryPoint/buildConfig/files 白名单），禁止清单外文件、符号链接、绝对路径与 `..`。
5. **事件上报全链路**：OFFERED → DOWNLOAD_STARTED/COMPLETED → VERIFY_SUCCEEDED/FAILED →
   INSTALL_STARTED/SUCCEEDED/FAILED，便于后台统计成功率与定位失败设备。

---

## 3. 客户端接入步骤

### 3.1 引入升级包

把 `client_update/` 整个包复制进你的项目，依赖仅 `requests` + `cryptography`（+ PyQt5，若用 qt_flow）。

### 3.2 编写 `config/client-update.json`

```json
{
  "enabled": true,
  "appId": 3,
  "bizCode": "ZHIBO_LIVE",
  "displayName": "智播豆",
  "version": "1.8.0",
  "channel": "STABLE",
  "updaterVersion": "1.0.0",
  "protocolVersion": 1,
  "platform": "WINDOWS",
  "arch": "X64",
  "entryPoint": "zhibodou.exe",
  "updaterExecutable": "zhibodou_updater.exe",
  "serverBaseUrl": "https://pdk.graddu.com",
  "healthTimeoutSeconds": 45,
  "artifactPublicKeys": { "client-release-2026-01": "<base64 DER Ed25519 公钥>" },
  "policyPublicKeys":   { "client-policy-2026-01":  "<base64 DER Ed25519 公钥>" }
}
```

约束（`config.py` 强校验，不符直接拒绝启动升级流程）：
- `version` / `updaterVersion` 必须是 `MAJOR.MINOR.PATCH`；`channel` 仅 `STABLE/BETA`；
- `entryPoint` 必须是安装目录内安全相对路径；`updaterExecutable` 必须是发布根目录的单个 EXE 文件名；
- **`version` 必须与代码内 `core/config.py` 的 `APP_VERSION` 一致**（qt_flow 启动时核对，不一致直接报错）——发版时两处同步改。

### 3.3 启动期编排（一行接入）

```python
from client_update.qt_flow import run_startup_update

# 登录窗出现之前、主窗口创建之后调用（device_id 用稳定设备标识）
result = run_startup_update(device_id, expected_version=APP_VERSION, parent=splash_or_none)
if not result.continue_startup:
    sys.exit(0)   # 强制升级/升级器已接管，主程序必须退出
```

`run_startup_update` 内部已处理：检查失败放行（无缓存的 REQUIRED 时）、REQUIRED 弹窗不可跳过、
下载进度条、拉起升级器后提示退出。

### 3.4 健康握手（必须接入，否则升级永远回滚）

新版程序启动早期调用：

```python
from client_update.health import mark_update_healthy

mark_update_healthy(APP_VERSION)   # 非升级器拉起时是无操作（no-op）
```

原理：升级器启动新版时注入 `PDK_UPDATE_HEALTH_FILE` / `PDK_UPDATE_HEALTH_NONCE` 环境变量；
新版若能正常执行到这一行并原子写入 `{version, nonce}` JSON，升级器即判定健康。
**建议放在初始化最前面**（能启动+能写文件即健康），不要放在登录成功之后——否则登录链路故障会触发无意义回滚。

### 3.5 环境变量参考

| 变量 | 作用 | 默认 |
|---|---|---|
| `PDK_UPDATE_BASE_URL` | 覆盖升级服务地址（测试用） | client-update.json 的 serverBaseUrl |
| `PDK_UPDATE_CONFIG` | 指定配置文件路径 | exe 同目录 → 仓库 config/ |
| `PDK_UPDATE_CACHE` | 覆盖缓存目录 | `%LOCALAPPDATA%\PDK\<appId>\updates` |
| `PDK_UPDATE_ENABLED` | 关闭升级检查 | json 的 enabled |
| `PDK_UPDATE_ARTIFACT/POLICY_PUBLIC_KEY` | 覆盖内置公钥（轮换应急） | json 的公钥表 |
| `PDK_INSTALL_ROOT` | 覆盖安装目录 | sys.executable 所在目录 |
| `PDK_UPDATE_HEALTH_FILE/NONCE` | 升级器注入，勿手工设置 | — |

---

## 4. 构建（打包 EXE）

用 `build_exe.py`（不要手写 PyInstaller 命令），它会：
1. 以 `main.py` 为入口打 onedir 包（`dist/zhibodou/zhibodou.exe` + `_internal/`）；
2. 把 `config/client-update.json` 放进发布根目录（运行时按 exe 同目录优先加载）；
3. 额外把 `client_update/updater.py` 打成独立 `zhibodou_updater.exe`（`--onefile --windowed`）放进发布根目录。

```bash
# 发布版（注入生产 BASE_URL https://pdk.graddu.com；调试版默认本地 8080）
python build_exe.py --release --windowed
```

**构建已知坑**：
- PyInstaller 6.x 跨盘路径（E: 源码 + C: 临时目录）在 makespec 阶段报
  `path is on mount 'E:'` —— 构建前 `set TMP/TEMP` 指到源码同盘目录；
- onefile 升级器无控制台，调试时先跑 `--onefile` 带控制台版本或直接看日志文件。

---

## 5. 发布流程（打升级包 + 后台上架）

### 5.1 打合规升级包 —— 必须用官方打包器

```bash
python E:\pdk\scripts\build_update_package.py ^
  --source E:\zhibodou\dist\zhibodou ^
  --output E:\zhibodou\dist\updates\zhibodou-1.8.0-windows-x64.zip ^
  --app-id 3 --version 1.8.0 --entry-point zhibodou.exe
```

打包器会：校验 `--source` 内嵌 `client-update.json` 与命令行参数一致（不一致直接拒绝）→
计算全部文件 SHA-256 → 生成**根目录 `update-manifest.json`**
（声明 appId/version/platform=WINDOWS/arch=X64/entryPoint/buildConfig=client-update.json/files 白名单）→ 输出 zip 与总 SHA-256。

> ⚠️ **绝对不要直接 zip dist 目录**：裸 zip 没有根目录清单，上传后台必被
> 「ZIP 根目录必须包含 update-manifest.json；以下参数必须与 Manifest 完全一致」拒绝。

### 5.2 后台上架三步（graddu）

1. **savePolicy（升级策略）**：注意绑定的是 **BIZ_ID，不是 appId**；声明目标版本、
   updatePolicy（REQUIRED/OPTIONAL）、minimumSupportedVersion、offlineGraceHours、签发/过期时间。
   未配置策略时 check 接口返回 `UPDATE_POLICY_NOT_CONFIGURED`。
2. **publish release（发布构件）**：上传第 5.1 步的 zip，后台填写参数必须与 Manifest 一致
   （appId=3 / version=1.8.0 / platform=WINDOWS / arch=X64 / entryPoint=zhibodou.exe）。
3. **rollout（灰度放量）**：按百分比放量，100% 即全量。

### 5.3 验证发布是否生效

```bash
curl "https://pdk.graddu.com/api/v1/client/updates/check?currentVersion=1.7.0&platform=WINDOWS&arch=X64&channel=STABLE&protocolVersion=1&updaterVersion=1.0.0" \
  -H "X-PDK-App-ID: 3" -H "X-PDK-Device-ID: test-device"
```

返回 `hasUpdate:true` + `targetVersion` + 已签名 artifact 即上架成功。

---

## 6. 升级器技术细节（安装阶段）

### 6.1 调用参数（由 manager.launch_updater 组装）

```
zhibodou_updater.exe --package <缓存zip> --install-root <exe所在目录>
  --version 1.8.0 --entry-point zhibodou.exe --app-id 3
  --platform WINDOWS --arch X64 --package-type ZIP
  --file-size <N> --sha256 <hex> --signature <base64> --public-key <base64>
  --parent-pid <主程序PID> --health-file <缓存路径> --health-nonce <hex>
  --health-timeout 45
```

环境变量：`PDK_UPDATER_DECISION_FILE`（pending-update.json，用于上报）、
`PDK_UPDATER_API_BASE`、`PDK_UPDATER_DEVICE_ID`。

### 6.2 版本替换双策略（WinError 32 的完整解法）

**优先：目录级原子替换**（`_switch_to_new_version`）
1. `install_root` → `.backup-<ts>`（重命名，3 次退避重试）；
2. `.staging` → `install_root`；
3. 任一步失败自动回滚。

**降级：逐文件就地同步**（目录被资源管理器/IDE/终端 CWD 等外部进程锁住目录句柄时）
1. 整目录 copytree 到备份；
2. 逐文件覆盖新版 + 删除旧版多余文件；新版中单个文件被独占时**报错精确到文件名**，便于定位残留程序；
3. 中途失败用备份就地恢复。

**进程树清理（防 ffmpeg/scrcpy/ADB 等孤儿子进程锁文件）**：
`_kill_process_tree(parent_pid)` 用 `CreateToolhelp32Snapshot` 枚举 + `TerminateProcess`。
保护集 = **自己 + 子孙 + 祖先链**。两个血泪坑：
- `descendants()` 天然不含起始 PID——不显式加 `self_pid` 会 TerminateProcess 自己；
- PyInstaller `--onefile` 升级器是 **bootloader(父) + python(子) 双进程**，bootloader 也是
  主程序的子进程，不保护祖先链会把整个升级器杀掉（现象：日志停在清理行后再无输出）。
主程序本身不强杀，退出交给 `wait_for_parent`（`OpenProcess/GetExitCodeProcess`，
勿用 `os.kill(pid,0)`——Windows 下 WinError 6）。

### 6.3 健康检查与回滚

- 通过 → 上报 `INSTALL_SUCCEEDED`、删备份与 pending-update.json；
- 45s 未通过/异常 → `rollback()`：原子模式用目录换回、就地模式用备份 sync 回，并拉起旧版 exe；
- 最终兜底：外层异常处理用备份就地恢复旧版。

### 6.4 日志与缓存

| 路径 | 内容 |
|---|---|
| `%LOCALAPPDATA%\PDK\updates\updater-YYYYMMDD.log` | 升级器全流程日志（排障第一入口） |
| `%LOCALAPPDATA%\PDK\<appId>\updates\artifact-<id>.zip` | 已下载升级包（支持断点续传） |
| `...\trusted-policy.json` | 已验签策略缓存（离线强制升级判定） |
| `...\pending-update.json` | 待安装决策（上报事件用，成功后删除） |
| 安装目录旁 `.<name>.backup-*` / `*.staging` / `*.failed-*` | 升级过程临时目录（成功后自动清理） |

---

## 7. 排障清单

| 现象 | 排查 |
|---|---|
| 不提示升级 | `serverBaseUrl` 指向；后台未 savePolicy（`UPDATE_POLICY_NOT_CONFIGURED`）；rollout 未放量/设备未命中灰度 |
| 上传后台被拒 | zip 必须由 `build_update_package.py` 生成，根目录含 manifest，后台参数与 Manifest 一致 |
| 下载 416 Range Not Satisfiable | 已修复（`existing==expected_size` 不发 Range；非 206 删部分文件全量重下）；确认客户端 manager.py 含该修复 |
| 点 OK 后无升级、无日志 | dist 是旧构建（不含修复），重新 `build_exe.py --release` |
| WinError 32 / 5 目录占用 | 关闭资源管理器窗口/编辑器对该目录的占用；升级器会自动降级就地同步，若仍失败日志会指出具体被锁文件名 |
| 日志突然中断 | 旧版升级器 kill-tree 自杀 bug；用 `d5c7b72` 之后的构建 |
| 升级后回滚 | 看日志 `健康检查未通过`——检查新版是否接入 `mark_update_healthy`，或新版启动即崩溃 |
| 版本配置不一致报错 | `core/config.py` 的 APP_VERSION 与 client-update.json 的 version 未同步 |

---

## 8. 发版 SOP（速查）

1. 改版本号：`core/config.py` APP_VERSION + `config/client-update.json` version（两处一致）；
2. `python build_exe.py --release --windowed`；
3. `python E:\pdk\scripts\build_update_package.py --source dist/zhibodou --output dist/updates/<name>.zip --app-id <id> --version <ver> --entry-point <exe>`；
4. 后台：savePolicy（BIZ_ID）→ publish release（上传 zip，参数对齐 Manifest）→ rollout 放量；
5. curl check 验证 → 低版本客户端实测升级 → 看 updater 日志确认 INSTALL_SUCCEEDED。

---

## 9. 跨语言 / 跨平台接入

### 9.1 资产分层：什么能复用，什么必须重写

| 层 | 内容 | 可复用性 |
|---|---|---|
| 服务端 | check/events 接口、策略与构件签名、打包器、后台管理 | **完全复用**，与客户端语言无关（HTTP + JSON + Ed25519） |
| 协议契约 | 接口字段、canonical 验签串（`PDK-POLICY-V1` / `PDK-ARTIFACT-V1` 的换行拼接顺序）、manifest 结构 | **完全复用**，但实现必须逐字节对齐 canonical 串，顺序错=验签失败 |
| 可移植客户端逻辑 | SHA-256 校验、Range 断点续传、清单校验、事件上报 | 复用思路，各语言 ~200-300 行即可实现 |
| 平台替换机制 | "如何替换正在运行的自己" | **必须按平台重写**，这是唯一强平台相关部分 |

关键认知：**升级器 `zhibodou_updater.exe` 本身就是语言无关的**——它通过命令行参数 + 环境变量驱动，
不关心调用者是什么语言写的。任何 Windows 程序（C++/C#/Electron/Go…）都可以直接复用它。

### 9.2 C++（Qt/MFC 等）Windows 桌面程序

**✅ 已有纯 C++ 原生升级器 SDK：`native_updater/`（2026-09-14 已与 Python 版对齐）**

- 定位：只覆盖「安装侧」（验签→替换→健康检查→回滚），检查/下载由宿主程序实现（HTTP + 200 行左右逻辑）；
- 产物：`pdk_updater.exe`（约 630KB，静态 CRT，无外部依赖；对比 Python 升级器 14MB）；
- 依赖：nlohmann/json、miniz、monocypher（CMake FetchContent 固定版本+哈希）；
- 构建：`cmake -S . -B build -G "Visual Studio 17 2022" -A x64 && cmake --build build --config Release`；
- 调用契约：`pdk_updater.exe --job <job.json>`（schemaVersion=1），job.json 字段：
  `schemaVersion/packagePath/installRoot/targetVersion/entryPoint/appId/platform/arch/packageType/
  fileSize/sha256/signature/publicKey/parentPid/healthFile/healthNonce/healthTimeoutSeconds/
  relaunchOnRollback` + 可选 `telemetry{endpoint,appId,deviceId,checkRequestId,eventToken,artifactId,fromVersion,targetVersion,platform}`；
- 安全实现与 Python 版逐项对齐：artifact canonical 验签（monocypher + SPKI 前缀剥离）、
  manifest 三方校验、路径安全白名单（比 Python 更严：盘符/尾部空格点/大小写冲突）、
  进程树清理（保护 self+子孙+祖先链）、原子替换→逐文件就地同步双策略、文件日志
  `%LOCALAPPDATA%\PDK\updates\native-updater-YYYYMMDD.log`；
- 已通过端到端实测：Python cryptography 签名 → C++ 验签（跨语言互操作）、
  原子替换、目录被占用自动降级就地同步、健康握手、临时目录清理。

**✅ 完整 C++ 参考实现：`update_tester/`（appId=4 测试客户端，2026-09-14 生产环境全链路验证通过）**

一个约 680 行、零第三方依赖（纯 Win32 + WinHTTP + BCrypt + CMake FetchContent 引 nlohmann/json/miniz/monocypher）
的完整客户端，覆盖 9.2 上述"检查/下载侧"全部四步，可直接作为各 C++ 程序接入的模板：

1. **检查**：WinHTTP 调 check 接口（`X-PDK-App-ID` / `X-PDK-Device-ID` 头），解析 hasUpdate/artifact/signature；
2. **下载**：`Range: bytes=<existing>-` 断点续传，非 206 回退全量；
3. **验签**：BCrypt 算 SHA-256 + monocypher 做 Ed25519 canonical 验签（与 native_updater 同一套 crypto 代码）；
4. **安装**：组装 job.json → 从缓存运行目录拉起 `pdk_updater.exe --job <job.json>` → 自己作为"新版"
   在启动时读 `PDK_UPDATE_HEALTH_FILE/NONCE` 完成健康握手。

实测流程（生产服务器）：check(hasUpdate) → 下载 0.5MB → SHA-256 → pdk_updater 验签 → kill-tree →
原子替换 → 健康握手 → 1.0.0 升至 1.1.0，一次通过。

**C++ 实现已知坑（血泪清单）**：
- **BCrypt 哈希对象缓冲必须按 `BCRYPT_OBJECT_LENGTH` 属性分配**，不能想当然用
  `hash_len * 4`——后者在小包上"碰巧能跑"，换缓冲大小后 `BCryptCreateHash` 静默失败、
  SHA-256 返回空串且 NTSTATUS 常被忽略。正确做法：查 `BCRYPT_OBJECT_LENGTH` + `BCRYPT_HASH_REUSABLE`，
  逐个 NTSTATUS 检查；
- `sha256_file` 别在栈上开大缓冲（1MiB 栈缓冲直接栈溢出，MSYS 下表现为 exit 127），用堆 `std::vector`；
- MSVC 命令行构建：VS SDK 库目录是 `Lib` 不是 `Libs`；沙箱/CI 里跑不了 `VsDevCmd.bat` 时用
  Ninja + 手动设 INCLUDE/LIB/PATH，或用仓库里的 `native_updater/build_native.bat`（VS 2022 生成器）；
- MSVC 链接 LNK1104 先确认上一次测试的 exe 进程没退出（等待 stdin 的控制台程序会锁住文件）。

**备选路径：直接复用 Python 升级器 exe**

C++ 端只需实现"检查 + 下载 + 验签 + 拉起升级器"四步：

1. HTTP 检查：libcurl / Qt `QNetworkAccessManager` 调 check 接口；
2. Ed25519 验签：**libsodium**（`crypto_sign_verify_detached`）或 OpenSSL 3.x；
   注意 canonical 串按 `security.py` 的字段顺序用 `\n` 拼接，公钥是 32 字节裸密钥的 base64
   （Python 端 `load_der_public_key` 接的是 DER SubjectPublicKeyInfo，服务端返回的 signature/public-key
   编码格式要与现有 Python 验签代码对齐后再在 C++ 里复刻）；
3. 下载断点续传：`Range: bytes=<existing>-` + 非 206 回退全量，与 `manager.py` 逻辑一致；
4. 拉起升级器：`CreateProcess` 复制 `zhibodou_updater.exe` 到临时目录，按 6.1 的 17 个参数组装命令行，
   设置 `PDK_UPDATER_DECISION_FILE / PDK_UPDATER_API_BASE / PDK_UPDATER_DEVICE_ID` 三个环境变量后退出主程序。
   健康握手：升级器会注入 `PDK_UPDATE_HEALTH_FILE/NONCE` 环境变量，新版 C++ 程序启动时把
   `{version, nonce}` JSON 原子写入该文件即可（几行 Win32 代码）。

**长期路径**：若要摆脱 Python 运行时（升级器 exe 目前 14MB，含 Python 解释器），可按
`updater.py` 的流程用 C++/Go/Rust 重写一个原生升级器（Go/Rust 单文件约 2-3MB），
协议完全不变，服务端无需任何改动。

### 9.3 Android

自更新架构完全不同——**不能替换正在运行的 APK**，只能交给系统安装器：

| 环节 | 做法 |
|---|---|
| 检查/决策 | 复用同一 check 接口；`REQUIRED` 策略在 App 启动时做**门禁**：版本 < minimumSupportedVersion 就拦截到全屏升级页，不进业务 |
| 下载 | DownloadManager 或 OkHttp 下到 `getExternalFilesDir()`；校验 SHA-256 + Ed25519（BouncyCastle / Conscrypt / Java 15+ 原生） |
| 安装 | `FileProvider` + `ACTION_INSTALL_PACKAGE` Intent 交给系统安装器（用户确认）；设备 Owner/系统签名场景可用 `PackageInstaller` 静默安装 |
| 商店分发 | 若走应用商店，更新本身由商店负责，客户端只用本协议做"强制升级门禁"（比较版本号后引导跳商店详情页） |
| 健康检查/回滚 | 不需要——Android 安装要么成功要么保持旧版，原子性由系统保证 |

### 9.4 iOS

**技术上无法自更新**，系统不允许替换已安装的 App Bundle。协议层的用法退化为"升级门禁"：

1. 启动时调同一 check 接口（网络层 URLSession）；
2. `REQUIRED` / 版本低于最低可运行版本 → 阻断业务，展示升级页；
3. 跳转 App Store：`SKStoreProductViewController` 或 `itms-apps://` 链接；
4. 实际下载安装、原子性、回滚全部由 App Store 负责，客户端只做版本号比较与 UI 拦截。

企业 In-House / TestFlight 分发同理（TestFlight 有自己的更新机制）。

### 9.5 macOS

直接用 **Sparkle 2** 框架——它内置 Ed25519 签名（EdDSA），与本方案的安全模型同源：
服务端补一个把 check 响应映射成 Sparkle appcast XML 的适配接口即可，客户端零自研。

### 9.6 各平台要点对照表

| 平台 | 替换机制 | Ed25519 库 | 强制更新落地 | 健康检查/回滚 |
|---|---|---|---|---|
| Windows (C++) | 独立升级器进程（原生 `pdk_updater.exe`，或复用 Python `zhibodou_updater.exe`） | BCrypt + monocypher / libsodium | 启动门禁 + 升级器强制安装 | 健康文件 + 自动回滚（升级器内置） |
| Windows (Python/PyQt) | 同上（参考实现） | cryptography | 同上 | 同上 |
| Android | 系统安装器 / PackageInstaller | BouncyCastle / Conscrypt | 启动门禁拦截页 | 系统保证原子性 |
| iOS | App Store 跳转 | CryptoKit（Curve25519） | 启动门禁拦截页 | App Store 保证 |
| macOS | Sparkle 2 | Sparkle 内置 EdDSA | Sparkle critical update 标记 | Sparkle 内置 |

### 9.7 落地建议

1. **先把协议固化成规范文档**（接口字段、canonical 串逐字节定义、manifest schema、事件类型枚举），
   放进服务端仓库并打版本号（当前 `protocolVersion=1`）——它是所有语言接入的唯一依据；
2. 服务端**不要为不同平台开不同协议**：platform/arch 字段已经做了隔离
   （WINDOWS/X64、ANDROID/ARM64…），同一套接口直接服务全平台；
3. 打包器按平台扩展：Android 出 APK/ 签名校验方式改为 Android 签名，iOS 无需构件分发（只下发策略），
   Windows 沿用现有 zip + manifest；
4. Windows 原生升级器已完成 C++ 版（`native_updater/` → `pdk_updater.exe`），无需再重写；
   新客户端语言接入时照抄 `update_tester/update_tester.cpp` 的"检查+下载+验签"模板即可。
