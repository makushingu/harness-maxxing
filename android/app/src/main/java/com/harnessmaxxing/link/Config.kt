package com.harnessmaxxing.link

import android.content.Context
import android.os.Build

/** Pairing and settings, in the app's private preferences (never backed up, see the manifest). */
class Config(context: Context) {
    private val prefs = context.getSharedPreferences("link", Context.MODE_PRIVATE)

    val server: String? get() = prefs.getString("server", null)
    val token: String? get() = prefs.getString("token", null)
    val deviceId: String? get() = prefs.getString("device_id", null)
    val paired: Boolean get() = !server.isNullOrEmpty() && !token.isNullOrEmpty()

    var name: String
        get() = prefs.getString("name", null)?.takeIf { it.isNotBlank() } ?: defaultName()
        set(v) = prefs.edit().putString("name", v.trim().take(64)).apply()

    var paused: Boolean
        get() = prefs.getBoolean("paused", false)
        set(v) = prefs.edit().putBoolean("paused", v).apply()

    fun savePairing(server: String, deviceId: String, token: String) {
        prefs.edit().putString("server", server).putString("device_id", deviceId)
            .putString("token", token).putBoolean("paused", false).commit()
    }

    /** Forget the server (Forget button, revoked token, `unpair`). The name is kept. */
    fun forget() {
        prefs.edit().remove("server").remove("device_id").remove("token").remove("paused").commit()
    }

    companion object {
        fun defaultName(): String {
            val model = Build.MODEL ?: "Android"
            val maker = Build.MANUFACTURER ?: ""
            return if (maker.isNotEmpty() && !model.lowercase().startsWith(maker.lowercase())) {
                "${maker.replaceFirstChar { it.uppercase() }} $model"
            } else model
        }
    }
}
