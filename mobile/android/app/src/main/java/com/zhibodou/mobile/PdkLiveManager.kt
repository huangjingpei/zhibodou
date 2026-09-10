package com.zhibodou.mobile

import com.zhibodou.mobile.camera.PdkOpenGlView

/**
 * 智播推流取景全局管理器
 * 负责打通 React Native ViewManager 创建的 PdkOpenGlView 真实渲染管线与 PdkLiveModule 推流控制器
 */
object PdkLiveManager {
    @Volatile
    var currentView: PdkOpenGlView? = null
        private set

    @Volatile
    var liveModule: PdkLiveModule? = null

    fun attachView(view: PdkOpenGlView) {
        currentView = view
        liveModule?.onViewAttached(view)
    }

    fun detachView(view: PdkOpenGlView) {
        if (currentView == view) {
            liveModule?.onViewDetached(view)
            currentView = null
        }
    }

    fun onSurfaceCreated(view: PdkOpenGlView) {
        liveModule?.onSurfaceCreated(view)
    }

    fun onSurfaceDestroyed(view: PdkOpenGlView) {
        liveModule?.onSurfaceDestroyed(view)
    }
}
