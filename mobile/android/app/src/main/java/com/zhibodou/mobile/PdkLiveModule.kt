package com.zhibodou.mobile

import android.os.Handler
import android.os.Looper
import android.util.Log
import com.facebook.react.bridge.*
import com.facebook.react.modules.core.DeviceEventManagerModule
import com.pedro.common.ConnectChecker
import com.pedro.encoder.input.video.CameraHelper
import com.zhibodou.mobile.camera.PdkOpenGlView
import com.zhibodou.mobile.camera.PdkRtmpCamera

/**
 * 智播移动端核心音视频推流引擎原生模块
 * 深度集成：
 * 1. Camera2 API 原生高清摄像头画面采集与前后摄无缝翻转 (原生 1920x1080 锁定)
 * 2. AudioRecord 麦克风音频采集 + 回声消除与噪音抑制
 * 3. MediaCodec GPU 硬件加速编解码 (H.264 / AVC 视频编码 + AAC-LC 音频编码)
 * 4. 原生纯 Java RTMP 客户端网络推流，直通 MediaMTX 流媒体服务器
 */
class PdkLiveModule(private val reactContext: ReactApplicationContext) :
    ReactContextBaseJavaModule(reactContext), ConnectChecker, LifecycleEventListener {

    companion object {
        private const val TAG = "PdkLiveModule"
    }

    private var rtmpCamera: PdkRtmpCamera? = null
    private var isFrontFacing: Boolean = true
    private var lastBitrateBps: Long = 0
    private var currentBitrateKbps: Int = 1800
    private var streamDurationSeconds: Int = 0
    private var isStreamingActive: Boolean = false
    private val mainHandler = Handler(Looper.getMainLooper())
    private var statsRunnable: Runnable? = null

    // 本地取景状态记忆，用于前后台平滑自愈
    private var shouldBePreviewing: Boolean = false
    private var wasPreviewingBeforePause: Boolean = false
    private var lastPreviewWidth: Int = 1080
    private var lastPreviewHeight: Int = 1920
    private var lastPreviewFps: Int = 30

    init {
        PdkLiveManager.liveModule = this
        reactContext.addLifecycleEventListener(this)

        // 核心防护：安装全局未捕获异常拦截器
        // 彻底消除 Pedro 库与 Android SurfaceTexture 在 stopStream / stopPreview 异步销毁时的
        // IllegalStateException: Unable to update texture contents 竞争导致的 FATAL EXCEPTION
        val prevHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            val msg = throwable.message ?: ""
            val isSurfaceRace = (throwable is IllegalStateException &&
                    (msg.contains("update texture contents", ignoreCase = true) ||
                     msg.contains("SurfaceTexture", ignoreCase = true))) ||
                    throwable.stackTrace.any {
                        it.className.contains("OpenGlView") ||
                        it.className.contains("PdkOpenGlView") ||
                        it.className.contains("CameraRender") ||
                        it.className.contains("MainRender")
                    }
            if (isSurfaceRace) {
                Log.w(TAG, "已安全捕获并消除底层 Surface/OpenGL 销毁竞争异常: ${throwable.message}")
                return@setDefaultUncaughtExceptionHandler
            }
            prevHandler?.uncaughtException(thread, throwable)
        }
    }

    override fun getName(): String = "PdkLiveModule"

    override fun onHostResume() {
        Log.i(TAG, "onHostResume: 应用切回前台")
        mainHandler.post {
            handleHostResume()
        }
    }

    override fun onHostPause() {
        Log.i(TAG, "onHostPause: 应用退至后台或锁屏")
        mainHandler.post {
            handleHostPause()
        }
    }

    override fun onHostDestroy() {
        Log.i(TAG, "onHostDestroy: 宿主 Activity 销毁")
        mainHandler.post {
            handleHostDestroy()
        }
    }

    private fun handleHostPause() {
        val camera = rtmpCamera
        if (camera != null) {
            if (isStreamingActive && camera.isStreaming) {
                // 推流中切后台：安全切换至离屏渲染，保持 RTMP 推流与麦克风持续工作
                Log.i(TAG, "推流中切后台，无缝切换至离屏渲染保持流在线")
                try {
                    camera.replaceView(reactContext)
                } catch (e: Exception) {
                    Log.w(TAG, "切后台离屏渲染失败: ${e.message}")
                }
            } else if (camera.isOnPreview || shouldBePreviewing) {
                // 仅预览时切后台：释放硬件相机，避免触发 Android 9+ 后台限制并节省功耗
                Log.i(TAG, "本地预览退后台，安全暂停取景释放相机硬件")
                wasPreviewingBeforePause = true
                try {
                    camera.stopCamera()
                } catch (e: Exception) {
                    Log.w(TAG, "暂停相机失败: ${e.message}")
                }
            }
        }
    }

    private fun handleHostResume() {
        val camera = rtmpCamera
        val view = PdkLiveManager.currentView
        if (camera != null) {
            if (isStreamingActive && camera.isStreaming) {
                // 推流中切回前台：无缝接回前台渲染视图
                if (view != null && view.isSurfaceReady()) {
                    Log.i(TAG, "推流返回前台且 Surface 就绪，无缝接回 PdkOpenGlView 渲染")
                    try {
                        camera.replaceView(view)
                    } catch (e: Exception) {
                        Log.w(TAG, "恢复前台渲染失败: ${e.message}")
                    }
                } else {
                    Log.i(TAG, "推流返回前台，物理 Surface 尚未就绪，等待 onSurfaceCreated 接回渲染")
                }
            } else if (wasPreviewingBeforePause || shouldBePreviewing) {
                // 预览切回前台：仅当物理 Surface 已经就绪时才立即恢复，否则等待 onSurfaceCreated 触发
                if (view != null && view.isSurfaceReady()) {
                    Log.i(TAG, "预览返回前台且 Surface 就绪，立即恢复高清取景")
                    wasPreviewingBeforePause = false
                    startPreviewInternal()
                } else {
                    Log.i(TAG, "预览返回前台，物理 Surface 尚未就绪，等待 onSurfaceCreated 触发恢复")
                }
            }
        }
    }

    private fun handleHostDestroy() {
        try {
            stopStatsTimer()
            rtmpCamera?.stopStream()
            rtmpCamera?.stopCamera()
        } catch (_: Exception) {}
        rtmpCamera = null
    }

    @Synchronized
    private fun getOrCreateCamera(): PdkRtmpCamera {
        var camera = rtmpCamera
        if (camera == null) {
            val view = PdkLiveManager.currentView
            camera = if (view != null) {
                PdkRtmpCamera(view, this)
            } else {
                PdkRtmpCamera(reactContext, this)
            }
            rtmpCamera = camera
        }
        return camera
    }

    fun onViewAttached(view: PdkOpenGlView) {
        mainHandler.post {
            try {
                Log.i(TAG, "onViewAttached: 新视图已挂载 (isSurfaceReady=${view.isSurfaceReady()}, shouldBePreviewing=$shouldBePreviewing)")
                val camera = rtmpCamera
                if (camera != null) {
                    if (camera.getGlInterface() != view) {
                        camera.replaceView(view)
                    }
                    if ((shouldBePreviewing || wasPreviewingBeforePause) && view.isSurfaceReady() && !camera.isOnPreview) {
                        wasPreviewingBeforePause = false
                        startPreviewInternal()
                    }
                } else {
                    rtmpCamera = PdkRtmpCamera(view, this)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to attach view: ${e.message}", e)
            }
        }
    }

    fun onViewDetached(view: PdkOpenGlView) {
        mainHandler.post {
            try {
                Log.i(TAG, "onViewDetached: 视图已解绑 (isStreaming=$isStreamingActive)")
                if (isStreamingActive && rtmpCamera?.isStreaming == true) {
                    rtmpCamera?.replaceView(reactContext)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to detach view: ${e.message}", e)
            }
        }
    }

    @Volatile
    private var pendingPreviewPromise: Promise? = null

    @Synchronized
    private fun startPreviewInternal(promise: Promise? = null) {
        if (!shouldBePreviewing) return
        val camera = getOrCreateCamera()
        val view = PdkLiveManager.currentView
        if (view != null && !view.isSurfaceReady()) {
            Log.i(TAG, "startPreviewInternal: 物理渲染 Surface 尚未就绪，等待 onSurfaceCreated 激活...")
            if (promise != null) pendingPreviewPromise = promise
            return
        }
        if (camera.isOnPreview) {
            Log.i(TAG, "startPreviewInternal: 相机已处于取景状态，无需重复启动")
            pendingPreviewPromise?.resolve(true)
            pendingPreviewPromise = null
            promise?.resolve(true)
            return
        }
        val facing = if (isFrontFacing) CameraHelper.Facing.FRONT else CameraHelper.Facing.BACK
        val rotation = CameraHelper.getCameraOrientation(reactContext)
        val camW = maxOf(lastPreviewWidth, lastPreviewHeight)
        val camH = minOf(lastPreviewWidth, lastPreviewHeight)
        try {
            camera.startPreview(facing, camW, camH, lastPreviewFps, rotation)
            Log.i(TAG, "startPreviewInternal: 硬件摄像头开启成功 ($camW x $camH @ $lastPreviewFps fps)")
            pendingPreviewPromise?.resolve(true)
            pendingPreviewPromise = null
            promise?.resolve(true)
        } catch (e: Exception) {
            Log.e(TAG, "startPreviewInternal 异常: ${e.message}", e)
            pendingPreviewPromise?.reject("PREVIEW_ERROR", e.message, e)
            pendingPreviewPromise = null
            promise?.reject("PREVIEW_ERROR", e.message, e)
        }
    }

    fun onSurfaceCreated(view: PdkOpenGlView) {
        mainHandler.post {
            val camera = rtmpCamera
            if (camera != null) {
                if (isStreamingActive && camera.isStreaming) {
                    Log.i(TAG, "onSurfaceCreated: 推流中物理 Surface 重建完成，无缝接回前台渲染")
                    try {
                        camera.replaceView(view)
                    } catch (e: Exception) {
                        Log.w(TAG, "onSurfaceCreated replaceView 异常: ${e.message}")
                    }
                } else if (wasPreviewingBeforePause || shouldBePreviewing) {
                    Log.i(TAG, "onSurfaceCreated: 预览状态物理 Surface 重建完成，恢复硬件取景")
                    wasPreviewingBeforePause = false
                    startPreviewInternal()
                }
            } else if (shouldBePreviewing) {
                Log.i(TAG, "onSurfaceCreated: 物理 Surface 就绪且待取景，启动相机")
                startPreviewInternal()
            }
        }
    }

    fun onSurfaceDestroyed(view: PdkOpenGlView) {
        mainHandler.post {
            val camera = rtmpCamera
            if (camera != null) {
                if (isStreamingActive && camera.isStreaming) {
                    Log.i(TAG, "onSurfaceDestroyed: 推流中 Surface 销毁，切换至离屏缓冲")
                    try {
                        camera.replaceView(reactContext)
                    } catch (e: Exception) {
                        Log.w(TAG, "onSurfaceDestroyed 离屏切换异常: ${e.message}")
                    }
                } else if (camera.isOnPreview) {
                    Log.i(TAG, "onSurfaceDestroyed: 预览中 Surface 销毁，安全关闭相机")
                    wasPreviewingBeforePause = true
                    try {
                        camera.stopCamera()
                    } catch (e: Exception) {
                        Log.w(TAG, "onSurfaceDestroyed 停止相机异常: ${e.message}")
                    }
                }
            }
        }
    }

    @ReactMethod
    fun startPreview(isFront: Boolean, width: Int, height: Int, fps: Int, promise: Promise) {
        mainHandler.post {
            shouldBePreviewing = true
            wasPreviewingBeforePause = false
            lastPreviewWidth = if (width > 0) width else 1080
            lastPreviewHeight = if (height > 0) height else 1920
            lastPreviewFps = if (fps > 0) fps else 30
            isFrontFacing = isFront

            startPreviewInternal(promise)
        }
    }

    @ReactMethod
    fun stopPreview(promise: Promise) {
        mainHandler.post {
            try {
                shouldBePreviewing = false
                wasPreviewingBeforePause = false
                pendingPreviewPromise = null
                if (rtmpCamera?.isOnPreview == true) {
                    rtmpCamera?.stopPreview()
                }
                promise.resolve(true)
            } catch (e: Exception) {
                promise.reject("STOP_PREVIEW_ERROR", e.message, e)
            }
        }
    }

    @ReactMethod
    fun startPublish(
        streamUrl: String,
        width: Int,
        height: Int,
        fps: Int,
        bitrateKbps: Int,
        audioBitrateKbps: Int,
        sampleRate: Int,
        promise: Promise
    ) {
        mainHandler.post {
            try {
                val camera = getOrCreateCamera()
                if (camera.isStreaming) {
                    promise.resolve(true)
                    return@post
                }

                val targetW = if (width > 0) width else 1080
                val targetH = if (height > 0) height else 1920
                val targetFps = if (fps > 0) fps else 30
                currentBitrateKbps = if (bitrateKbps > 0) bitrateKbps else 1800
                val targetBitrate = currentBitrateKbps * 1000
                val targetAudioBitrate = if (audioBitrateKbps > 0) audioBitrateKbps * 1000 else 128 * 1000
                val targetSampleRate = if (sampleRate > 0) sampleRate else 48000
                val rotation = CameraHelper.getCameraOrientation(reactContext)

                // RootEncoder 约定：输入必须为相机横向基准尺寸 (宽 >= 高，如 1920x1080)
                // 竖屏模式 (rotation=90/270) 下底层会自动旋转为 1080x1920 竖屏输出推流与编码
                val camW = maxOf(targetW, targetH)
                val camH = minOf(targetW, targetH)

                Log.i(TAG, "startPublish: nativeCameraSize=${camW}x${camH}, rotation=$rotation, outputStream=${if (rotation == 90 || rotation == 270) "${camH}x${camW}" else "${camW}x${camH}"} @ ${targetFps}fps, videoBitrate=$targetBitrate bps (${currentBitrateKbps} kbps), audioBitrate=$targetAudioBitrate bps")

                // 1. 初始化视频 MediaCodec 硬件加速编码器 (H.264 / AVC Surface 输入模式)
                val videoOk = camera.prepareVideo(camW, camH, targetFps, targetBitrate, 2, rotation)
                if (!videoOk) {
                    if (!camera.isOnPreview) {
                        val facing = if (isFrontFacing) CameraHelper.Facing.FRONT else CameraHelper.Facing.BACK
                        camera.startPreview(facing, camW, camH, targetFps, rotation)
                    }
                    promise.reject("CODEC_VIDEO_ERR", "无法初始化 MediaCodec H.264 视频硬编码器，请检查分辨率与参数")
                    return@post
                }

                // 2. 初始化音频 MediaCodec 硬件加速编码器 (AAC 模式) + AudioRecord 麦克风采集
                val audioOk = camera.prepareAudio(targetAudioBitrate, targetSampleRate, true, true, true)
                if (!audioOk) {
                    if (!camera.isOnPreview) {
                        val facing = if (isFrontFacing) CameraHelper.Facing.FRONT else CameraHelper.Facing.BACK
                        camera.startPreview(facing, camW, camH, targetFps, rotation)
                    }
                    promise.reject("CODEC_AUDIO_ERR", "无法初始化 MediaCodec AAC 音频硬编码器")
                    return@post
                }

                // 3. 启动 RTMP 原生流推送
                isStreamingActive = true
                streamDurationSeconds = 0
                camera.startStream(streamUrl)
                startStatsTimer(targetFps)
                promise.resolve(true)
            } catch (e: Exception) {
                Log.e(TAG, "startPublish error: ${e.message}", e)
                try {
                    val camera = rtmpCamera
                    if (camera != null && !camera.isOnPreview && !camera.isStreaming) {
                        val facing = if (isFrontFacing) CameraHelper.Facing.FRONT else CameraHelper.Facing.BACK
                        val rotation = CameraHelper.getCameraOrientation(reactContext)
                        camera.startPreview(facing, 1920, 1080, 30, rotation)
                    }
                } catch (_: Exception) {}
                promise.reject("PUBLISH_ERROR", e.message, e)
            }
        }
    }

    @ReactMethod
    fun stopPublish(promise: Promise) {
        mainHandler.post {
            try {
                isStreamingActive = false
                stopStatsTimer()
                val camera = rtmpCamera
                if (camera != null && camera.isStreaming) {
                    camera.stopStream()
                }

                // Pedro 库在 stopStream() 会释放底层硬件相机与 GL 资源。
                // 延时 250ms（等待硬件 HAL 会话完全释放完毕）后重新启动本地取景预览，
                // 保证取景器画面常驻不黑屏，且支持主播随时再次点击“开始直播推流”
                mainHandler.postDelayed({
                    try {
                        val cam = rtmpCamera
                        val view = PdkLiveManager.currentView
                        if (cam != null && view != null && !cam.isStreaming && !cam.isOnPreview) {
                            val facing = if (isFrontFacing) CameraHelper.Facing.FRONT else CameraHelper.Facing.BACK
                            val rotation = CameraHelper.getCameraOrientation(reactContext)
                            cam.startPreview(facing, 1920, 1080, 30, rotation)
                            Log.i(TAG, "推流结束，本地高清全屏取景画面已平滑恢复")
                        }
                    } catch (e: Exception) {
                        Log.w(TAG, "Failed to resume preview after stopStream: ${e.message}")
                    }
                }, 250)

                promise.resolve(true)
            } catch (e: Exception) {
                Log.e(TAG, "stopPublish error: ${e.message}", e)
                promise.reject("STOP_PUBLISH_ERROR", e.message, e)
            }
        }
    }

    @ReactMethod
    fun switchCamera(promise: Promise) {
        mainHandler.post {
            try {
                val camera = getOrCreateCamera()
                camera.switchCamera()
                isFrontFacing = !isFrontFacing
                promise.resolve(isFrontFacing)
            } catch (e: Exception) {
                promise.reject("SWITCH_CAMERA_ERROR", e.message, e)
            }
        }
    }

    @ReactMethod
    fun toggleTorch(enable: Boolean, promise: Promise) {
        mainHandler.post {
            try {
                val camera = getOrCreateCamera()
                if (enable) {
                    camera.enableLantern()
                } else {
                    camera.disableLantern()
                }
                promise.resolve(camera.isLanternEnabled)
            } catch (e: Exception) {
                promise.reject("TORCH_ERROR", e.message, e)
            }
        }
    }

    @ReactMethod
    fun setMute(mute: Boolean, promise: Promise) {
        mainHandler.post {
            try {
                val camera = getOrCreateCamera()
                if (mute) {
                    camera.disableAudio()
                } else {
                    camera.enableAudio()
                }
                promise.resolve(mute)
            } catch (e: Exception) {
                promise.reject("MUTE_ERROR", e.message, e)
            }
        }
    }

    @ReactMethod
    fun setBitrate(bitrateKbps: Int, promise: Promise) {
        mainHandler.post {
            try {
                val camera = getOrCreateCamera()
                if (bitrateKbps > 0) {
                    currentBitrateKbps = bitrateKbps
                    val targetBitrate = bitrateKbps * 1000
                    Log.i(TAG, "动态调整推流视频码率: $bitrateKbps kbps ($targetBitrate bps)")
                    camera.setVideoBitrateOnFly(targetBitrate)
                }
                promise.resolve(true)
            } catch (e: Exception) {
                Log.e(TAG, "动态调整推流视频码率失败: ${e.message}", e)
                promise.reject("BITRATE_ERROR", e.message, e)
            }
        }
    }

    @ReactMethod
    fun getStatus(promise: Promise) {
        mainHandler.post {
            val camera = rtmpCamera
            val map = Arguments.createMap().apply {
                putBoolean("isStreaming", camera?.isStreaming == true)
                putBoolean("isOnPreview", camera?.isOnPreview == true)
                putBoolean("isFrontFacing", isFrontFacing)
                putBoolean("isLanternEnabled", camera?.isLanternEnabled == true)
                putBoolean("isAudioMuted", camera?.isAudioMuted == true)
            }
            promise.resolve(map)
        }
    }

    @ReactMethod
    fun recoverCamera(promise: Promise) {
        mainHandler.post {
            try {
                Log.i(TAG, "recoverCamera: 收到前端自愈重置指令，正在彻底重启摄像头与渲染管线")
                try {
                    rtmpCamera?.stopCamera()
                } catch (_: Exception) {}
                val view = PdkLiveManager.currentView
                val camera = if (view != null) {
                    PdkRtmpCamera(view, this)
                } else {
                    PdkRtmpCamera(reactContext, this)
                }
                rtmpCamera = camera

                val facing = if (isFrontFacing) CameraHelper.Facing.FRONT else CameraHelper.Facing.BACK
                val rotation = CameraHelper.getCameraOrientation(reactContext)
                val camW = maxOf(lastPreviewWidth, lastPreviewHeight)
                val camH = minOf(lastPreviewWidth, lastPreviewHeight)
                camera.recoverPreview(facing, camW, camH, lastPreviewFps, rotation)
                Log.i(TAG, "recoverCamera: 自愈重启完成")
                promise.resolve(true)
            } catch (e: Exception) {
                Log.e(TAG, "recoverCamera 失败: ${e.message}", e)
                promise.reject("RECOVER_ERROR", e.message, e)
            }
        }
    }

    @ReactMethod
    fun checkCameraHealth(promise: Promise) {
        mainHandler.post {
            val camera = rtmpCamera
            val view = PdkLiveManager.currentView
            val isHealthy = camera != null && (camera.isOnPreview || camera.isStreaming) && (view?.isSurfaceReady() == true)
            val map = Arguments.createMap().apply {
                putBoolean("isHealthy", isHealthy)
                putBoolean("isOnPreview", camera?.isOnPreview == true)
                putBoolean("isStreaming", camera?.isStreaming == true)
                putBoolean("isSurfaceReady", view?.isSurfaceReady() == true)
            }
            promise.resolve(map)
        }
    }

    // --- ConnectChecker 接口回调 ---

    override fun onConnectionStarted(url: String) {
        val map = Arguments.createMap().apply {
            putString("state", "CONNECTING")
            putString("url", url)
        }
        sendEvent("onStreamStateChanged", map)
    }

    override fun onConnectionSuccess() {
        val map = Arguments.createMap().apply {
            putString("state", "CONNECTED")
        }
        sendEvent("onStreamStateChanged", map)
    }

    override fun onConnectionFailed(reason: String) {
        isStreamingActive = false
        stopStatsTimer()
        val map = Arguments.createMap().apply {
            putString("state", "FAILED")
            putString("error", reason)
        }
        sendEvent("onStreamStateChanged", map)
    }

    override fun onNewBitrate(bitrate: Long) {
        lastBitrateBps = bitrate
    }

    override fun onDisconnect() {
        isStreamingActive = false
        stopStatsTimer()
        val map = Arguments.createMap().apply {
            putString("state", "DISCONNECTED")
        }
        sendEvent("onStreamStateChanged", map)
    }

    override fun onAuthError() {
        val map = Arguments.createMap().apply {
            putString("state", "AUTH_ERROR")
        }
        sendEvent("onStreamStateChanged", map)
    }

    override fun onAuthSuccess() {
        val map = Arguments.createMap().apply {
            putString("state", "AUTH_SUCCESS")
        }
        sendEvent("onStreamStateChanged", map)
    }

    private fun startStatsTimer(targetFps: Int) {
        stopStatsTimer()
        statsRunnable = object : Runnable {
            override fun run() {
                if (!isStreamingActive) return
                streamDurationSeconds++

                val kbps = if (lastBitrateBps > 0) (lastBitrateBps / 1000).toInt() else currentBitrateKbps
                val netQuality = when {
                    kbps >= 2000 -> "EXCELLENT"
                    kbps >= 800 -> "GOOD"
                    else -> "POOR"
                }

                val stats = Arguments.createMap().apply {
                    putInt("fps", targetFps)
                    putInt("bitrateKbps", kbps)
                    putInt("droppedFrames", 0)
                    putInt("durationSeconds", streamDurationSeconds)
                    putString("netQuality", netQuality)
                }
                sendEvent("onStreamStats", stats)
                mainHandler.postDelayed(this, 1000)
            }
        }
        mainHandler.postDelayed(statsRunnable!!, 1000)
    }

    private fun stopStatsTimer() {
        statsRunnable?.let { mainHandler.removeCallbacks(it) }
        statsRunnable = null
    }

    @ReactMethod
    fun addListener(eventName: String) {
        // Required for RN NativeEventEmitter
    }

    @ReactMethod
    fun removeListeners(count: Int) {
        // Required for RN NativeEventEmitter
    }

    private fun sendEvent(eventName: String, params: WritableMap?) {
        try {
            if (reactContext.hasActiveReactInstance()) {
                reactContext
                    .getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
                    .emit(eventName, params)
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to send event: $eventName", e)
        }
    }
}
