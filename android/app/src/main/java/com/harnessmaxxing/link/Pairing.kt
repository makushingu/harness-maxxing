package com.harnessmaxxing.link

import android.content.Context
import android.os.Build
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

/** `POST <server>/api/devices/pair` -> `{device_id, token}`, saved in [Config]. Blocking. */
object Pairing {
    sealed class Result {
        data object Ok : Result()
        data class Failed(val reason: Reason, val detail: String = "") : Result()
    }

    enum class Reason { BAD_SERVER, BAD_CODE, EXPIRED, NETWORK, SERVER }

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS).readTimeout(20, TimeUnit.SECONDS).build()

    fun pair(context: Context, rawServer: String, rawCode: String): Result {
        val server = try {
            PairLink.normalizeServer(rawServer, BuildConfig.DEBUG)
        } catch (e: PairLink.BadServer) {
            return Result.Failed(Reason.BAD_SERVER, e.message ?: "")
        }
        val code = PairLink.cleanCode(rawCode)
        if (code.isEmpty()) return Result.Failed(Reason.BAD_CODE)
        val config = Config(context)
        val body = Protocol.pairBody(code, config.name, Build.SUPPORTED_ABIS.firstOrNull() ?: "unknown", BuildConfig.VERSION_NAME)
        val req = Request.Builder().url(PairLink.pairUrl(server))
            .header("User-Agent", "HarnessLink-Android/${BuildConfig.VERSION_NAME}")
            .post(body.toRequestBody("application/json".toMediaType()))
            .build()
        return try {
            client.newCall(req).execute().use { resp ->
                val text = resp.body.string()
                when {
                    resp.isSuccessful -> {
                        val r = Protocol.parsePairReply(text) ?: return Result.Failed(Reason.SERVER, "bad reply")
                        config.savePairing(server, r.deviceId, r.token)
                        Result.Ok
                    }
                    resp.code == 410 || Protocol.pairError(text).contains("expired") -> Result.Failed(Reason.EXPIRED)
                    resp.code in 400..499 -> Result.Failed(Reason.BAD_CODE)
                    else -> Result.Failed(Reason.SERVER, "HTTP ${resp.code}")
                }
            }
        } catch (e: Exception) {
            Result.Failed(Reason.NETWORK, e.javaClass.simpleName)
        }
    }
}
