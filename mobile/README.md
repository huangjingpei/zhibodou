# 智播豆移动端 (Zhibodou Mobile) - 跨平台音视频推流客户端

基于 **React Native + TypeScript** 架构打造的现代化移动端音视频开播客户端，原生支持 **Android** 与 **iOS** 双平台。

完整对齐 **PDK 商业化云控平台 (`appId=3 / ZHIBO_LIVE`)** 业务协议，具备设备许可证绑定、`40380` 卡密自动激活、短效 RTMP 票据申请、`40971` 遗留流自愈以及专业级音视频参数调控能力。

---

## 一、 核心功能与界面特性

1. **现代化暗黑录制室视觉 (Dark Studio UI)**：
   * 沉浸式暗色界面（Slate / Cyan / Neon Red），打造专业级电竞/主播视觉质感。
2. **全屏高清取景与对焦交互**：
   * 全屏摄像头预览取景框，支持构图九宫格辅助线；
   * 轻触屏幕触发自然测光对焦方框动画；
   * **镜头平滑反转 (Flip Camera)**：支持一键在 **前置自拍镜像** 与 **后置高清主摄** 间无缝切换。
3. **顶部悬浮流状态看板 (Live HUD)**：
   * 动态呼吸红光 `LIVE` 徽标；
   * 直播累计时长实时计时器（时:分:秒）；
   * 实时动态性能指示胶囊：分辨率、实时推流帧率 (FPS)、上行码率 (kbps)、网络健康度；
   * 右侧快捷入口：主播手机号脱敏展示与个人中心快速跳转。
4. **现代化浮动操作工具栏**：
   * 🔄 **镜头翻转**：切换前置自拍 / 后置超清镜头；
   * 🎙️ **麦克风静音**：一键切换静音与拾音，画面显示防错水印；
   * 💡 **闪光补光灯**：后置镜头时支持开启手电筒常亮补光；
   * ⚙️ **参数抽屉**：一键呼出底部毛玻璃画质设置抽屉；
   * 🔴 **核心开播胶囊**：带光效的超宽交互大按钮，自动完成鉴权、申请推流票据与推流启动。
5. **底部画质参数调节抽屉 (Settings Sheet)**：
   * **分辨率档位切换**：`1080P 超清 (1080x1920)` / `720P 高清 (720x1280)` / `540P 标清 (540x960)`；
   * **视频码率预设**：`6000 kbps (旗舰画质)` / `3500 kbps (推荐标准)` / `1800 kbps (弱网流畅)`；
   * **推流目标帧率**：`60 FPS (丝滑极高帧)` / `30 FPS (通用标准帧)`；
   * **运行环境即时切换**：生产环境 (`https://pdk.graddu.com`) 与本地联调 (`http://127.0.0.1:8080`)。
6. **设备许可证席位与安全管理**：
   * 自动生成稳定设备唯一指纹 (`MOB-AND-xxxxxxxx` / `MOB-IOS-xxxxxxxx`)；
   * 首次在未授权移动设备登录时，自动拦截 `40380` 并滑出“设备卡密激活”层，输入卡密一键完成 1:1 设备席位绑定；
   * 个人中心提供当前席位状态、到期时间、剩余调用次数查看，以及**一键解绑当前设备席位**能力。

---

## 二、 工程目录结构

```text
E:\zhibodou\mobile/
├── package.json                          # 项目元数据与依赖配置
├── tsconfig.json                         # TypeScript 严格类型检查规则
├── babel.config.js                       # Babel 转换配置
├── index.js                              # React Native AppRegistry 入口
├── App.tsx                               # 应用根组件与全局状态路由
├── src/
│   ├── api/
│   │   ├── pdkClient.ts                  # PDK 核心通信 SDK (登录/激活/票据/停止)
│   │   └── types.ts                      # 全局 TypeScript 接口与模型定义
│   ├── components/
│   │   ├── CameraViewfinder.tsx          # 全屏摄像头取景框 (镜像反转、网格线、对焦圈)
│   │   ├── LiveOverlayHud.tsx            # 顶部悬浮流状态 HUD (LIVE徽标、计时、码率、帧率)
│   │   ├── StreamControlBar.tsx          # 现代化底部浮动操作工具栏 (翻转、静音、补光、开播)
│   │   └── SettingsSheet.tsx             # 底部毛玻璃画质与环境调节抽屉
│   ├── screens/
│   │   ├── LoginScreen.tsx               # 登录与 40380 设备卡密激活页面
│   │   ├── LiveScreen.tsx                # 直播主控室核心大屏
│   │   └── ProfileScreen.tsx             # 个人中心、卡密详情与设备解绑页面
│   ├── services/
│   │   ├── deviceService.ts              # 跨平台稳定设备指纹 UUID 维护器
│   │   ├── liveService.ts                # 推流票据申请编排与 40971 冲突自愈器
│   │   └── rtmpEngine.ts                 # RTMP 推流适配与统计采样引擎
│   └── theme/
│       ├── colors.ts                     # 现代暗色直播间配色设计规范
│       └── typography.ts                 # 字体、排版与间距设计规范
├── android/                              # 标准 Android Studio 原生工程
│   ├── build.gradle
│   ├── settings.gradle
│   └── app/
│       ├── build.gradle
│       └── src/main/
│           ├── AndroidManifest.xml       # 相机、麦克风、网络与前台保活服务权限
│           └── java/com/zhibodou/mobile/
│               ├── MainActivity.kt
│               └── MainApplication.kt
└── ios/                                  # 标准 iOS Xcode 原生工程
    ├── Podfile
    └── ZhibodouMobile/
        ├── Info.plist                    # 相机与麦克风隐私授权文案
        ├── AppDelegate.h / .mm
        └── main.m
```

---

## 三、 快速启动与编译运行

### 1. 依赖安装
在 `E:\zhibodou\mobile` 目录下执行：
```bash
npm install
```

### 2. 代码质量与类型检查
```bash
npm run typecheck
```

### 3. Android 端运行
1. 确保电脑已安装 Android SDK 或 Android Studio，并连接真机或启动模拟器；
2. 执行以下命令：
```bash
npm run android
```
或者直接在 Android Studio 中打开 `E:\zhibodou\mobile\android` 工程进行构建与断点调试。

### 4. iOS 端运行 (需 macOS 环境)
1. 安装 CocoaPods 依赖：
```bash
cd ios && pod install && cd ..
```
2. 执行运行命令：
```bash
npm run ios
```
或者在 Xcode 中打开 `E:\zhibodou\mobile\ios\ZhibodouMobile.xcworkspace` 运行在 iPhone 真机上。

---

## 四、 PDK 业务协议对接技术细节

* **服务发现**：`appId = 3`, `bizCode = "ZHIBO_LIVE"`
* **认证路径**：`POST /api/v1/client/auth/login`
  - 请求体：`{ appId: 3, phone, password, deviceId, cardKey? }`
  - 返回动态 `tokenName` 与 `tokenValue`（保存在会话头 `satoken: <value>`）。
* **推流票据与自愈机制**：
  - 调用 `POST /api/v1/client/zhibo-live/streams/push-ticket` 获取短效 `publishUrl`；
  - 遇到 `40971`（上场直播断线遗留活动流）时，`liveService` 自动执行清理旧流并延时重试，主播开播 100% 顺畅。
