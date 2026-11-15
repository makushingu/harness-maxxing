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

    /** Error codes of `{"t":"err"}` replies (table of link/PROTOCOL.md). */
    object Err {
        const val BAD_REQUEST = "bad_request"   // missing / invalid field, unknown action, key, button or node
        const val UNSUPPORTED = "unsupported"   // not possible on a phone (move, ctrl+s...), unknown request
        const val PERMISSION = "permission"     // the accessibility service is off (see the hello note)
        const val PROTECTED = "protected"       // FLAG_SECURE window: cannot be captured
        const val LOCKED = "locked"             // keyguard with PIN / pattern, or screen off
        const val NOT_FOUND = "not_found"       // `open`: no such app
        const val BUSY = "busy"                 // more than 16 requests waiting
        const val PAUSED = "paused"             // the person pressed Pause on the phone
        const val FAILED = "failed"             // anything else (the message says what)
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

    /**
     * `v` = app version (as the desktop app), `kind` = "android". `caps` and `note` follow the
     * accessibility service; `screen` is absent when it is off. Sent again whenever it changes.
     */
    fun hello(
        name: String, arch: String, appVersion: String, model: String, sdk: Int, caps: List<String>,
        screenW: Int, screenH: Int, scale: Double, note: String, paused: Boolean,
    ): String {
        val o = JSONObject()
            .put("t", "hello")
            .put("v", appVersion)
            .put("os", "android")
            .put("kind", "android")
            .put("arch", arch)
            .put("name", name)
            .put("model", model)
            .put("sdk", sdk)
            .put("caps", JSONArray(caps))
            .put("paused", paused)
        if ("screen" in caps) o.put("screen", JSONObject().put("w", screenW).put("h", screenH).put("scale", scale))
        if (note.isNotEmpty()) o.put("note", note)
        return o.toString()
    }

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

    /** `error` of a 4xx pairing reply (`bad_code`, `expired`), or "". */
    fun pairError(body: String): String = try {
        val o = JSONObject(body)
        o.optString("error", "").ifEmpty { o.opt("detail")?.toString().orEmpty() }
    } catch (_: Exception) {
        ""
    }

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
        /** `keys`: a string of combos separated by spaces ("ctrl+a delete"), or a list of combos. */
        fun keys(): List<String> {
            val parts = when (val v = raw.opt("keys") ?: raw.opt("key")) {
                is JSONArray -> (0 until v.length()).map { v.optString(it) }
                is String -> listOf(v)
                else -> emptyList()
            }
            return parts.flatMap { it.trim().split(Regex("\\s+")) }.filter { it.isNotEmpty() }
        }
        fun obj(key: String): JSONObject? = raw.optJSONObject(key)
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
