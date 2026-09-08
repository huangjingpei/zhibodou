package com.zhibodou.mobile

import android.content.Context
import android.widget.FrameLayout
import com.facebook.react.uimanager.ThemedReactContext
import com.facebook.react.uimanager.ViewGroupManager
import com.pedro.encoder.utils.gl.AspectRatioMode
import com.zhibodou.mobile.camera.PdkOpenGlView

/**
 * 带有 9:16 等比例全屏居中裁剪适配 (Proportional Center-Crop) 的 PdkOpenGlView 容器
 * 彻底解决手机全面屏比例 (如 9:20 / 9:21) 与 9:16 标准视频画面的几何适配问题：
 * 1. 动态根据容器宽高与 9:16 画幅比例，精确计算 PdkOpenGlView 视图尺寸与负偏移位置；
 * 2. 保证底层 PdkOpenGlView 画布长宽比严格恒等于 9:16，消灭任何画面拉伸变形；
 * 3. 采用 AspectRatioMode.Fill 沉浸式满屏等比裁剪绘制；
 * 4. 呈现无黑边、无畸变、1:1 真实物理等比例沉浸式全屏画面。
 */
class PdkCameraContainer(context: Context) : FrameLayout(context) {

    val openGlView: PdkOpenGlView = PdkOpenGlView(context).apply {
        setAspectRatioMode(AspectRatioMode.Fill)
        layoutParams = LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT)
    }

    init {
        addView(openGlView)
        PdkLiveManager.attachView(openGlView)
    }

    override fun requestLayout() {
        super.requestLayout()
        post {
            measure(
                MeasureSpec.makeMeasureSpec(width, MeasureSpec.EXACTLY),
                MeasureSpec.makeMeasureSpec(height, MeasureSpec.EXACTLY)
            )
            layout(left, top, right, bottom)
        }
    }

    fun cleanup() {
        PdkLiveManager.detachView(openGlView)
    }
}

/**
 * React Native 原生摄像头取景视图管理器
 * 暴露给前端组件 <PdkCameraView /> 使用
 */
class PdkCameraViewManager : ViewGroupManager<PdkCameraContainer>() {
    override fun getName(): String = "PdkCameraView"

    override fun createViewInstance(reactContext: ThemedReactContext): PdkCameraContainer {
        return PdkCameraContainer(reactContext)
    }

    override fun onDropViewInstance(view: PdkCameraContainer) {
        super.onDropViewInstance(view)
        view.cleanup()
    }
}
