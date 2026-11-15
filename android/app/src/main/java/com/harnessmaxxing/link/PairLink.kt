package com.harnessmaxxing.link

import java.net.URI
import java.net.URLDecoder

/** Pairing link `harnesslink://pair?s=<server>&c=<code>` and server address rules. */
object PairLink {
    /** Hosts allowed over plain http, in debug builds only (emulator host, this phone). */
    val DEV_HOSTS = setOf("10.0.2.2", "localhost", "127.0.0.1")

    data class Link(val server: String, val code: String)

    class BadServer(message: String) : Exception(message)

    fun parse(link: String): Link? {
        val uri = try { URI(link.trim()) } catch (_: Exception) { return null }
        if (!uri.scheme.equals("harnesslink", true) || !uri.host.equals("pair", true)) return null
        val q = query(uri.rawQuery ?: return null)
        val s = q["s"]?.takeIf { it.isNotBlank() } ?: return null
        val c = q["c"]?.let(::cleanCode)?.takeIf { it.isNotEmpty() } ?: return null
        return Link(s.trim(), c)
    }

    /** Codes are shown as AB12CD34 (sometimes grouped): drop spaces and dashes. */
    fun cleanCode(code: String): String = code.filterNot { it.isWhitespace() || it == '-' }

    /**
     * Normalised server address (`https://host[:port][/path]`, no trailing slash).
     * HTTPS only; http is accepted for [DEV_HOSTS] when [allowDevHttp] (debug builds).
     */
    fun normalizeServer(raw: String, allowDevHttp: Boolean): String {
        var s = raw.trim()
        if (s.isEmpty()) throw BadServer("empty")
        if (!s.contains("://")) s = "https://$s"
        val uri = try { URI(s) } catch (_: Exception) { throw BadServer("invalid address") }
        val scheme = uri.scheme?.lowercase() ?: throw BadServer("invalid address")
        val host = uri.host?.lowercase() ?: throw BadServer("invalid address")
        if (uri.rawUserInfo != null) throw BadServer("invalid address")
        when (scheme) {
            "https" -> {}
            "http" -> if (!(allowDevHttp && host in DEV_HOSTS)) throw BadServer("https required")
            else -> throw BadServer("https required")
        }
        val port = if (uri.port > 0) ":${uri.port}" else ""
        val path = (uri.rawPath ?: "").trimEnd('/')
        val h = if (host.contains(':')) "[$host]" else host
        return "$scheme://$h$port$path"
    }

    fun pairUrl(server: String) = "$server/api/devices/pair"

    fun wsUrl(server: String): String = when {
        server.startsWith("https://") -> "wss://" + server.removePrefix("https://")
        server.startsWith("http://") -> "ws://" + server.removePrefix("http://")
        else -> server
    } + "/api/devices/ws"

    fun host(server: String): String = try { URI(server).host ?: server } catch (_: Exception) { server }

    private fun query(raw: String): Map<String, String> = raw.split('&').mapNotNull {
        val i = it.indexOf('=')
        if (i <= 0) null else {
            val k = URLDecoder.decode(it.substring(0, i), "UTF-8")
            val v = URLDecoder.decode(it.substring(i + 1), "UTF-8")
            k to v
        }
    }.toMap()
}
