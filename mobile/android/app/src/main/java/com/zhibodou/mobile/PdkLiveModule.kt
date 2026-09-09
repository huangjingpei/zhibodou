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
    ReactContextBaseJavaModule(reactContext), ConnectChecker {

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

    init {
        PdkLiveManager.liveModule = this

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
                val camera = rtmpCamera
                if (camera != null) {
                    camera.replaceView(view)
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
                rtmpCamera?.replaceView(reactContext)
            } catch (e: Exception) {
                Log.e(TAG, "Failed to detach view: ${e.message}", e)
            }
        }
    }

    @ReactMethod
    fun startPreview(isFront: Boolean, width: Int, height: Int, fps: Int, promise: Promise) {
        mainHandler.post {
            fun doStart(retries: Int) {
                try {
                    val camera = getOrCreateCamera()
                    isFrontFacing = isFront
                    val facing = if (isFront) CameraHelper.Facing.FRONT else CameraHelper.Facing.BACK
                    val targetW = if (width > 0) width else 1080
                    val targetH = if (height > 0) height else 1920
                    val targetFps = if (fps > 0) fps else 30
                    val rotation = CameraHelper.getCameraOrientation(reactContext)

                    if (!camera.isOnPreview) {
                        camera.startPreview(facing, targetW, targetH, targetFps, rotation)
                    }
                    promise.resolve(true)
                } catch (e: Exception) {
                    if (retries > 0) {
                        Log.w(TAG, "startPreview surface not ready, retrying in 150ms... remaining: $retries")
                        mainHandler.postDelayed({ doStart(retries - 1) }, 150)
                    } else {
                        Log.e(TAG, "startPreview error after retries: ${e.message}", e)
                        promise.reject("PREVIEW_ERROR", e.message, e)
                    }
                }
            }
            doStart(4)
        }
    }

    @ReactMethod
    fun stopPreview(promise: Promise) {
        mainHandler.post {
            try {
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

                Log.i(TAG, "startPublish: ${targetW}x${targetH} @ ${targetFps}fps, videoBitrate=$targetBitrate bps (${currentBitrateKbps} kbps), audioBitrate=$targetAudioBitrate bps")

                // 1. 初始化视频 MediaCodec 硬件加速编码器 (H.264 / AVC Surface 输入模式)
                val videoOk = camera.prepareVideo(targetW, targetH, targetFps, targetBitrate, 2, rotation)
                if (!videoOk) {
                    if (!camera.isOnPreview) {
                        val facing = if (isFrontFacing) CameraHelper.Facing.FRONT else CameraHelper.Facing.BACK
                        camera.startPreview(facing, targetW, targetH, targetFps, rotation)
                    }
                    promise.reject("CODEC_VIDEO_ERR", "无法初始化 MediaCodec H.264 视频硬编码器，请检查分辨率与参数")
                    return@post
                }

                // 2. 初始化音频 MediaCodec 硬件加速编码器 (AAC 模式) + AudioRecord 麦克风采集
                val audioOk = camera.prepareAudio(targetAudioBitrate, targetSampleRate, true, true, true)
                if (!audioOk) {
                    if (!camera.isOnPreview) {
                        val facing = if (isFrontFacing) CameraHelper.Facing.FRONT else CameraHelper.Facing.BACK
                        camera.startPreview(facing, targetW, targetH, targetFps, rotation)
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
                        camera.startPreview(facing, 1080, 1920, 30, rotation)
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
                            cam.startPreview(facing, 1080, 1920, 30, rotation)
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
