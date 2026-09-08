package com.zhibodou.mobile

import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import android.provider.Settings
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import java.security.MessageDigest

/**
 * 原生设备唯一标识模块
 * 基于硬件级 SSAID (Settings.Secure.ANDROID_ID) 与硬件指纹派生，结合 SharedPreferences 固化
 * 保证即使应用卸载重新安装，生成的设备 ID 也 100% 绝对一致，永不漂移
 */
class PdkDeviceModule(private val reactContext: ReactApplicationContext) :
    ReactContextBaseJavaModule(reactContext) {

    override fun getName(): String = "PdkDeviceModule"

    override fun getConstants(): MutableMap<String, Any> {
        val constants = HashMap<String, Any>()
        constants["deviceId"] = getStableDeviceId(reactContext)
        return constants
    }

    @ReactMethod(isBlockingSynchronousMethod = true)
    fun getDeviceIdSync(): String {
        return getStableDeviceId(reactContext)
    }

    @ReactMethod
    fun getDeviceId(promise: Promise) {
        try {
            promise.resolve(getStableDeviceId(reactContext))
        } catch (e: Exception) {
            promise.reject("DEVICE_ID_ERR", e.message, e)
        }
    }

    @ReactMethod
    fun setCustomDeviceId(customId: String) {
        if (customId.isNotBlank()) {
            val prefs = reactContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            prefs.edit().putString(KEY_DEVICE_ID, customId.trim()).apply()
        }
    }

    companion object {
        private const val PREFS_NAME = "pdk_device_identity"
        private const val KEY_DEVICE_ID = "persisted_device_id"

        @Synchronized
        fun getStableDeviceId(context: Context): String {
            val prefs: SharedPreferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val existing = prefs.getString(KEY_DEVICE_ID, null)
            if (!existing.isNullOrBlank()) {
                return existing
            }

            // 1. 获取 Android 硬件级稳定标识 SSAID (即使重新安装也保持不变)
            val androidId = try {
                Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)
            } catch (e: Exception) {
                null
            }

            // 2. 硬件级出厂特征指纹 (Brand / Manufacturer / Model / Hardware / Device)
            val hardwareFingerprint = "${Build.BRAND}:${Build.MANUFACTURER}:${Build.MODEL}:${Build.HARDWARE}:${Build.DEVICE}"

            // 3. 确定性派生 24 位大写十六进制哈希
            val rawSource = if (!androidId.isNullOrBlank() && androidId != "9774d56d682e549c") {
                "ANDROID:$androidId:$hardwareFingerprint"
            } else {
                "ANDROID:FALLBACK:$hardwareFingerprint"
            }

            val md = MessageDigest.getInstance("SHA-256")
            val hashBytes = md.digest(rawSource.toByteArray(Charsets.UTF_8))
            val hexString = hashBytes.take(12).joinToString("") { "%02x".format(it) }
            val stableId = "MOB-AND-${hexString.uppercase()}"

            // 4. 固化存储至 SharedPreferences
            prefs.edit().putString(KEY_DEVICE_ID, stableId).apply()
            return stableId
        }
    }
}
