package com.harnessmaxxing.link

import org.json.JSONArray
import org.json.JSONObject

/**
 * Harness Link protocol v2 (see link/PROTOCOL.md in the repository): JSON text frames on the
 * websocket. The server sends commands with an `id` it chooses; the phone answers
 * `{"t":"ok","id":...}` or `{"t":"err","id":...,"code":...,"message":...}`.
 */
object Protocol {
    const val VERSION = 2
    val CAPS = listOf("screen", "input", "tree", "apps")

    /** Error codes sent in `{"t":"err"}` replies. */
    object Err {
        const val PAUSED = "paused"                  // the user pressed Pause on the phone
        const val NO_ACCESSIBILITY = "no_accessibility" // the accessibility service is off
        const val PROTECTED = "protected"            // FLAG_SECURE window: the screen cannot be captured
        const val LOCKED = "locked"                  // keyguard with PIN/pattern, or screen off
        const val BAD_REQUEST = "bad_request"        // missing or invalid field
        const val UNSUPPORTED = "unsupported"        // unknown command, action or key
        const val NO_FOCUS = "no_focus"              // `type` / `key enter` without a focused text field
        const val STALE = "stale"                    // node id unknown or gone: ask for a new tree
        const val NOT_FOUND = "not_found"            // `open`: no such app
        const val TIMEOUT = "timeout"                // the system did not answer in time
        const val FAILED = "failed"                  // the system refused the action
    }

    fun ok(id: Any?, extra: JSONObject? = null): String {
        val o = extra ?: JSONObject()
        o.put("t", "ok")
        o.put("id", id ?: JSONObject.NULL)
        return o.toString()
    }

    fun err(id: Any?, code: String, message: String): String =
        JSONObject().put("t", "err").put("id", id ?: JSONObject.NULL).put("code", code)
            .put("message", message).toString()

    fun paused(on: Boolean): String = JSONObject().put("t", "paused").put("on", on).toString()

    fun hello(
        name: String, arch: String, appVersion: String, model: String, sdk: Int,
        screenW: Int, screenH: Int, scale: Double, note: String, paused: Boolean,
    ): String = JSONObject()
        .put("t", "hello")
        .put("v", VERSION)
        .put("os", "android")
        .put("arch", arch)
        .put("name", name)
        .put("version", appVersion)
        .put("model", model)
        .put("sdk", sdk)
        .put("caps", JSONArray(CAPS))
        .put("screen", JSONObject().put("w", screenW).put("h", screenH).put("scale", scale))
        .put("note", note)
        .put("paused", paused)
        .toString()

    /** Body of `POST /api/devices/pair`. */
    fun pairBody(code: String, name: String, arch: String, appVersion: String): String = JSONObject()
        .put("code", code)
        .put("name", name)
        .put("os", "android")
        .put("arch", arch)
        .put("version", appVersion)
        .put("caps", JSONArray(CAPS))
        .toString()

    data class PairResult(val deviceId: String, val token: String)

    fun parsePairReply(body: String): PairResult? = try {
        val o = JSONObject(body)
        val id = o.optString("device_id", "")
        val token = o.optString("token", "")
        if (id.isEmpty() || token.isEmpty()) null else PairResult(id, token)
    } catch (_: Exception) {
        null
    }

    /** One frame received from the server. `raw` keeps every field for the handlers. */
    class Frame(val t: String, val id: Any?, val raw: JSONObject) {
        fun str(key: String): String? = if (raw.has(key) && !raw.isNull(key)) raw.optString(key) else null
        fun num(key: String): Double? = if (raw.has(key) && !raw.isNull(key)) {
            val v = raw.opt(key)
            when (v) {
                is Number -> v.toDouble()
                is String -> v.toDoubleOrNull()
                else -> null
            }
        } else null
        fun int(key: String): Int? = num(key)?.toInt()
        fun bool(key: String): Boolean = when (val v = raw.opt(key)) {
            is Boolean -> v
            is Number -> v.toInt() != 0
            is String -> v == "true" || v == "1"
            else -> false
        }
        /** `keys` may be a string ("enter") or a list (["enter"]). */
        fun keys(): List<String> = when (val v = raw.opt("keys") ?: raw.opt("key") ?: raw.opt("text")) {
            is JSONArray -> (0 until v.length()).map { v.optString(it) }.filter { it.isNotBlank() }
            is String -> if (v.isBlank()) emptyList() else listOf(v)
            else -> emptyList()
        }
    }

    /** Parse a text frame; null when it is not a JSON object with a `t`. */
    fun parse(text: String): Frame? = try {
        val o = JSONObject(text)
        val t = o.optString("t", "")
        if (t.isEmpty()) null else Frame(t, if (o.has("id") && !o.isNull("id")) o.get("id") else null, o)
    } catch (_: Exception) {
        null
    }
}
