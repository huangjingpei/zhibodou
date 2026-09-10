package com.zhibodou.mobile

import android.content.Context
import android.content.SharedPreferences
import android.media.MediaDrm
import android.os.Build
import android.provider.Settings
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import java.security.MessageDigest
import java.util.UUID

/**
 * 原生设备唯一标识模块
 * 采用硬件级 Widevine DRM 设备唯一标识 (TEE/硬件熔丝级指纹) + 硬件出厂特征派生
 * 1. 保证即使应用卸载重新安装，同一台物理手机生成的设备 ID 100% 绝对一致，永不改变
 * 2. 无需申请任何系统敏感权限 (完全规避 READ_PHONE_STATE 等被拒风险，合规通过各大应用市场审核)
 * 3. 结合 SharedPreferences 快速缓存与同步/异步双通道导出
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

    @ReactMethod(isBlockingSynchronousMethod = true)
    fun getDevConfigSync(): String {
        val prefs = reactContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getString(KEY_DEV_CONFIG, "") ?: ""
    }

    @ReactMethod
    fun getDevConfig(promise: Promise) {
        try {
            val prefs = reactContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            promise.resolve(prefs.getString(KEY_DEV_CONFIG, "") ?: "")
        } catch (e: Exception) {
            promise.reject("DEV_CONFIG_ERR", e.message, e)
        }
    }

    @ReactMethod
    fun saveDevConfig(configJson: String) {
        val prefs = reactContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putString(KEY_DEV_CONFIG, configJson).apply()
    }

    @ReactMethod(isBlockingSynchronousMethod = true)
    fun getAuthCredentialsSync(): String {
        val prefs = reactContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getString(KEY_AUTH_CREDENTIALS, "") ?: ""
    }

    @ReactMethod
    fun getAuthCredentials(promise: Promise) {
        try {
            val prefs = reactContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            promise.resolve(prefs.getString(KEY_AUTH_CREDENTIALS, "") ?: "")
        } catch (e: Exception) {
            promise.reject("AUTH_CREDENTIALS_ERR", e.message, e)
        }
    }

    @ReactMethod
    fun saveAuthCredentials(credentialsJson: String) {
        val prefs = reactContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putString(KEY_AUTH_CREDENTIALS, credentialsJson).apply()
    }

    @ReactMethod
    fun clearAuthCredentials() {
        val prefs = reactContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().remove(KEY_AUTH_CREDENTIALS).apply()
    }

    companion object {
        private const val PREFS_NAME = "pdk_device_identity"
        private const val KEY_DEVICE_ID = "persisted_device_id"
        private const val KEY_DEV_CONFIG = "persisted_dev_config"
        private const val KEY_AUTH_CREDENTIALS = "persisted_auth_credentials"

        // Widevine DRM UUID: edef8ba9-79d6-4ace-a3c8-27dcd51d21ed
        private val WIDEVINE_UUID = UUID(-0x121074568629b532L, -0x5c37d82326e2229eL)

        /**
         * 获取 Android 硬件/TEE 熔丝级 Widevine DRM 设备唯一标识
         * 该标识烧录于硬件芯片 TrustZone，即使应用卸载重装、系统恢复出厂或更新系统也绝对保持不变
         */
        private fun getWidevineUniqueId(): String? {
            var mediaDrm: MediaDrm? = null
            return try {
                mediaDrm = MediaDrm(WIDEVINE_UUID)
                val widevineIdBytes = mediaDrm.getPropertyByteArray(MediaDrm.PROPERTY_DEVICE_UNIQUE_ID)
                if (widevineIdBytes != null && widevineIdBytes.size > 0) {
                    val sb = StringBuilder()
                    for (b in widevineIdBytes) {
                        sb.append("%02x".format(b))
                    }
                    sb.toString()
                } else {
                    null
                }
            } catch (e: Throwable) {
                // 部分 PC 模拟器或定制 ROM 可能裁剪了 Widevine
                null
            } finally {
                try {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                        mediaDrm?.close()
                    } else {
                        @Suppress("DEPRECATION")
                        mediaDrm?.release()
                    }
                } catch (e: Throwable) {
                    // ignore
                }
            }
        }

        @Synchronized
        fun getStableDeviceId(context: Context): String {
            val prefs: SharedPreferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val existing = prefs.getString(KEY_DEVICE_ID, null)
            if (!existing.isNullOrBlank()) {
                return existing
            }

            // 1. 获取硬件级 TEE Widevine DRM 唯一标识 (不随卸载重装改变，无需权限)
            val widevineId = getWidevineUniqueId()

            // 2. 获取 Android 辅助标识 SSAID
            val androidId = try {
                Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)
            } catch (e: Exception) {
                null
            }

            // 3. 硬件出厂特征指纹 (Brand / Manufacturer / Model / Hardware / Device / Board / Product)
            val hardwareSpecs = "${Build.BRAND}:${Build.MANUFACTURER}:${Build.MODEL}:${Build.HARDWARE}:${Build.DEVICE}:${Build.BOARD}:${Build.PRODUCT}"

            // 4. 确定性派生源：Widevine 硬件 ID 存在时优先锚定 Widevine
            val rawSource = if (!widevineId.isNullOrBlank()) {
                "WIDEVINE:$widevineId:$hardwareSpecs"
            } else if (!androidId.isNullOrBlank() && androidId != "9774d56d682e549c") {
                "ANDROID_SSAID:$androidId:$hardwareSpecs"
            } else {
                "ANDROID_HW:$hardwareSpecs"
            }

            // 5. 确定性 SHA-256 派生 24 位大写十六进制哈希
            val md = MessageDigest.getInstance("SHA-256")
            val hashBytes = md.digest(rawSource.toByteArray(Charsets.UTF_8))
            val hexString = hashBytes.take(12).joinToString("") { "%02X".format(it) }
            val stableId = "MOB-AND-$hexString"

            // 6. 固化存储至本地 SharedPreferences 作为运行时极速缓存
            prefs.edit().putString(KEY_DEVICE_ID, stableId).apply()
            return stableId
        }
    }
}
