package com.harnessmaxxing.link

import android.os.Handler
import android.os.Looper
import java.util.concurrent.CopyOnWriteArraySet

/** Live state of the link, observed by the main screen and the notification. */
object LinkState {
    enum class Conn { NOT_PAIRED, CONNECTING, CONNECTED, OFFLINE }

    @Volatile var conn: Conn = Conn.NOT_PAIRED
        private set
    @Volatile var busyBy: String? = null   // "claude" | "human" while the server uses the phone
        private set
    @Volatile var lastError: String? = null
        private set

    private val main = Handler(Looper.getMainLooper())
    private val listeners = CopyOnWriteArraySet<() -> Unit>()

    fun set(conn: Conn, error: String? = lastError) {
        this.conn = conn
        this.lastError = if (conn == Conn.CONNECTED) null else error
        if (conn != Conn.CONNECTED) busyBy = null
        notifyChanged()
    }

    fun setBusy(by: String?) {
        busyBy = by
        notifyChanged()
    }

    fun notifyChanged() {
        main.post { listeners.forEach { it() } }
    }

    fun observe(l: () -> Unit) { listeners.add(l) }
    fun unobserve(l: () -> Unit) { listeners.remove(l) }
}
