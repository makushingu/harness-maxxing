package com.harnessmaxxing.link

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.Network
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.SystemClock
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * Foreground service (type specialUse) that keeps the websocket to the Harness server open,
 * with the permanent notification and its Pause / Resume action. Commands run one at a time on
 * a worker thread and go to [LinkAccessibilityService].
 */
class LinkService : Service() {

    private lateinit var config: Config
    private val client: OkHttpClient = OkHttpClient.Builder()
        .pingInterval(30, TimeUnit.SECONDS)
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private val worker = Executors.newSingleThreadExecutor()
    private lateinit var loopThread: HandlerThread
    private lateinit var loop: Handler   // connection state machine: all changes happen here
    private val backoff = Backoff()

    private var ws: WebSocket? = null
    private var generation = 0
    private var stopped = false
    private var connectedAt = 0L
    private var lastHello: String? = null
    private val waiting = AtomicInteger(0)
    private val reconnect = Runnable { connect() }
    /** The hello is sent again whenever it changes (rotation, accessibility, name, pause). */
    private val helloCheck = object : Runnable {
        override fun run() {
            sendHelloIfChanged()
            loop.postDelayed(this, 30_000)
        }
    }

    private val netCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            loop.post {
                if (ws == null && !stopped) {
                    loop.removeCallbacks(reconnect)
                    backoff.reset()
                    connect()
                }
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        config = Config(this)
        loopThread = HandlerThread("link").also { it.start() }
        loop = Handler(loopThread.looper)
        goForeground()
        LinkState.observe(stateListener)
        try {
            getSystemService(ConnectivityManager::class.java).registerDefaultNetworkCallback(netCallback)
        } catch (_: Exception) {}
    }

    private val stateListener: () -> Unit = { updateNotification() }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        goForeground()
        val action = intent?.action
        loop.post { handleAction(action) }
        return START_STICKY
    }

    private fun handleAction(action: String?) {
        if (!config.paired) { shutdown(null); return }
        stopped = false
        when (action) {
            ACTION_PAUSE -> setPaused(true)
            ACTION_RESUME -> setPaused(false)
            ACTION_FORGET -> { config.forget(); shutdown(null); return }
            ACTION_RECONNECT, ACTION_ACCESSIBILITY_CHANGED -> {
                if (ws != null && LinkState.conn == LinkState.Conn.CONNECTED) sendHelloIfChanged()
                else { backoff.reset(); connectSoon(0) }
                return
            }
        }
        if (ws == null && !loop.hasCallbacks(reconnect)) connect()
    }

    // ---- connection ----------------------------------------------------------------------

    private fun connect() {
        if (stopped) return
        val server = config.server
        val token = config.token
        if (server == null || token == null) { shutdown(null); return }
        val gen = ++generation
        LinkState.set(LinkState.Conn.CONNECTING)
        val req = Request.Builder().url(PairLink.wsUrl(server))
            .header("Authorization", "Bearer $token")
            .header("User-Agent", "HarnessLink-Android/${BuildConfig.VERSION_NAME}")
            .build()
        ws = client.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) = loop.post {
                if (gen != generation) return@post
                connectedAt = SystemClock.elapsedRealtime()
                LinkState.set(LinkState.Conn.CONNECTED)
                lastHello = hello()
                webSocket.send(lastHello!!)
                if (config.paused) webSocket.send(Protocol.paused(true))
                loop.removeCallbacks(helloCheck)
                loop.postDelayed(helloCheck, 30_000)
            }.let {}

            override fun onMessage(webSocket: WebSocket, text: String) {
                if (gen != generation) return
                val f = Protocol.parse(text) ?: return
                // Run one at a time, in order; at most 16 waiting.
                if (f.id != null && f.t in COMMANDS && waiting.get() >= MAX_WAITING) {
                    webSocket.send(Protocol.err(f.id, Protocol.Err.BUSY, "Too many requests waiting"))
                    return
                }
                waiting.incrementAndGet()
                worker.execute {
                    try { handle(webSocket, gen, f) } finally { waiting.decrementAndGet() }
                }
            }

            fun closed(webSocket: WebSocket, code: Int) {
                loop.post { if (gen == generation && ws === webSocket) onDown(code == 4401 || code == 4403, "closed $code") }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
                closed(webSocket, code)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = closed(webSocket, code)

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                val code = response?.code
                response?.close()
                loop.post {
                    if (gen != generation || ws !== webSocket) return@post
                    onDown(code == 401 || code == 403, if (code != null) "HTTP $code" else t.javaClass.simpleName)
                }
            }
        })
    }

    private fun onDown(revoked: Boolean, why: String) {
        ws = null
        loop.removeCallbacks(helloCheck)
        // The backoff starts over only after a connection that lasted 30 s.
        if (connectedAt > 0 && SystemClock.elapsedRealtime() - connectedAt >= 30_000) backoff.reset()
        connectedAt = 0
        if (revoked) {
            Log.i(TAG, "token refused by the server ($why): forgetting the pairing")
            config.forget()
            shutdown("revoked")
            return
        }
        if (stopped) return
        LinkState.set(LinkState.Conn.OFFLINE, why)
        connectSoon(backoff.next())
    }

    private fun connectSoon(ms: Long) {
        loop.removeCallbacks(reconnect)
        loop.postDelayed(reconnect, ms)
    }

    private fun closeSocket() {
        generation++
        ws?.close(1000, null)
        ws = null
    }

    private fun sendHelloIfChanged() {
        val socket = ws ?: return
        if (LinkState.conn != LinkState.Conn.CONNECTED) return
        val h = hello()
        if (h != lastHello) {
            lastHello = h
            socket.send(h)
        }
    }

    private fun hello(): String {
        val size = Screen.realSize(this)
        val a11y = LinkAccessibilityService.enabled
        val note = when {
            !a11y -> "Accessibility is off: the phone cannot be seen or used until the person turns on the Harness Link accessibility service"
            config.paused -> "Paused on the phone"
            else -> ""
        }
        val caps = if (a11y) Protocol.CAPS else listOf("apps")
        return Protocol.hello(
            name = config.name,
            arch = Build.SUPPORTED_ABIS.firstOrNull() ?: "unknown",
            appVersion = BuildConfig.VERSION_NAME,
            model = Config.defaultName(),
            sdk = Build.VERSION.SDK_INT, caps = caps,
            screenW = size.w, screenH = size.h, scale = Screen.density(this),
            note = note, paused = config.paused,
        )
    }

    // ---- commands ------------------------------------------------------------------------

    private fun handle(socket: WebSocket, gen: Int, f: Protocol.Frame) {
        val reply: String? = try {
            run(f)
        } catch (e: CmdError) {
            Protocol.err(f.id, e.code, e.message ?: e.code)
        } catch (e: Exception) {
            Log.w(TAG, "command ${f.t} failed", e)
            Protocol.err(f.id, Protocol.Err.FAILED, "${e.javaClass.simpleName}: ${e.message ?: ""}".trim())
        }
        if (reply != null && gen == generation) socket.send(reply)
    }

    private fun svc(): LinkAccessibilityService = LinkAccessibilityService.instance
        ?: throw CmdError(Protocol.Err.PERMISSION, "The accessibility service of Harness Link is off: the person must turn it on in the app")

    /** Returns the reply frame, or null for messages without a reply. */
    private fun run(f: Protocol.Frame): String? {
        when (f.t) {
            "state" -> {
                LinkState.setBusy(if (f.bool("busy")) f.str("by") ?: "claude" else null)
                return null
            }
            "unpair" -> {
                loop.post { config.forget(); shutdown("revoked") }
                return null
            }
        }
        if (f.t !in COMMANDS) {
            return if (f.id != null) Protocol.err(f.id, Protocol.Err.UNSUPPORTED, "Unknown command: ${f.t}") else null
        }
        if (config.paused) throw CmdError(Protocol.Err.PAUSED, "The person paused Harness Link on the phone")
        val extra: JSONObject? = when (f.t) {
            "shot" -> svc().shot(f.int("max_w"), f.int("quality"), f.obj("crop"), f.int("sw"), f.int("sh"))
            "input" -> { svc().input(f); null }
            "tree" -> svc().tree(f.int("sw"), f.int("sh"))
            "tap_node" -> { svc().tapNode(f.int("node")); null }
            "set_text" -> {
                svc().setText(f.int("node"), f.str("text") ?: throw CmdError(Protocol.Err.BAD_REQUEST, "missing text"))
                null
            }
            "apps" -> {
                val arr = JSONArray()
                Apps.list(this).forEach { arr.put(JSONObject().put("id", it.id).put("name", it.name)) }
                JSONObject().put("apps", arr)
            }
            "open" -> {
                svc().open(f.str("app") ?: throw CmdError(Protocol.Err.BAD_REQUEST, "missing app"))
                null
            }
            else -> null
        }
        return Protocol.ok(f.id, extra)
    }

    private fun setPaused(on: Boolean) {
        config.paused = on
        ws?.send(Protocol.paused(on))
        sendHelloIfChanged()
        LinkState.notifyChanged()
    }

    private fun shutdown(error: String?) {
        stopped = true
        loop.removeCallbacks(reconnect)
        closeSocket()
        LinkState.set(LinkState.Conn.NOT_PAIRED, error)
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        stopped = true
        LinkState.unobserve(stateListener)
        try {
            getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(netCallback)
        } catch (_: Exception) {}
        loop.post { closeSocket() }
        loopThread.quitSafely()
        worker.shutdownNow()
        if (LinkState.conn != LinkState.Conn.NOT_PAIRED) LinkState.set(LinkState.Conn.OFFLINE)
        super.onDestroy()
    }

    // ---- notification --------------------------------------------------------------------

    private fun goForeground() {
        val n = buildNotification()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIFICATION_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTIFICATION_ID, n)
        }
    }

    private fun updateNotification() {
        if (stopped) return
        try {
            NotificationManagerCompat.from(this).notify(NOTIFICATION_ID, buildNotification())
        } catch (_: SecurityException) {
            // Notifications not allowed (Android 13+): the service still runs.
        }
    }

    private fun buildNotification(): Notification {
        val paused = ::config.isInitialized && config.paused
        val text = getString(when {
            paused -> R.string.notif_paused
            LinkState.conn != LinkState.Conn.CONNECTED -> R.string.notif_connecting
            LinkState.busyBy == "claude" -> R.string.notif_claude
            LinkState.busyBy == "human" -> R.string.notif_human
            else -> R.string.notif_connected
        })
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val toggle = PendingIntent.getService(
            this, 1, Intent(this, LinkService::class.java).setAction(if (paused) ACTION_RESUME else ACTION_PAUSE),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return NotificationCompat.Builder(this, LinkApp.CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setContentIntent(open)
            .addAction(0, getString(if (paused) R.string.resume else R.string.pause), toggle)
            .build()
    }

    companion object {
        private const val TAG = "HarnessLink"
        private const val NOTIFICATION_ID = 1
        const val ACTION_PAUSE = "com.harnessmaxxing.link.PAUSE"
        const val ACTION_RESUME = "com.harnessmaxxing.link.RESUME"
        const val ACTION_FORGET = "com.harnessmaxxing.link.FORGET"
        const val ACTION_RECONNECT = "com.harnessmaxxing.link.RECONNECT"
        const val ACTION_ACCESSIBILITY_CHANGED = "com.harnessmaxxing.link.ACCESSIBILITY"
        private const val MAX_WAITING = 16
        private val COMMANDS = setOf("shot", "input", "tree", "tap_node", "set_text", "apps", "open")

        fun start(context: Context, action: String? = null) {
            val i = Intent(context, LinkService::class.java)
            if (action != null) i.action = action
            try {
                context.startForegroundService(i)
            } catch (e: Exception) {
                // Background start refused (Android 12+): the next app launch or accessibility bind retries.
                Log.w(TAG, "cannot start the link service now: ${e.javaClass.simpleName}")
            }
        }
    }
}
