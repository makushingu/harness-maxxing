package com.harnessmaxxing.link

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.os.SystemClock
import android.util.Base64
import android.view.Display
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * The only part of the app that touches the screen. Every method blocks (it is called from the
 * link's worker thread, never the main thread) and throws [CmdError] on refusal.
 * It does exactly what the protocol lists: capture, gestures, text in a field, global keys,
 * the accessibility tree, launching an app. No shell, no files, no URLs.
 */
class LinkAccessibilityService : AccessibilityService() {

    private val shotExecutor = Executors.newSingleThreadExecutor()

    /** Nodes of the last `tree`, by id (ids are only valid for that snapshot). */
    @Volatile private var lastNodes: Map<Int, AccessibilityNodeInfo> = emptyMap()

    /** Capture space of the last shot, used when an input or a tree does not give `sw`/`sh`. */
    @Volatile var lastShot: Geometry.Size? = null
        private set

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        LinkState.notifyChanged()
        // A bound accessibility service may start a foreground service from the background.
        if (Config(this).paired) LinkService.start(this, LinkService.ACTION_ACCESSIBILITY_CHANGED)
    }

    override fun onUnbind(intent: Intent?): Boolean {
        clear()
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        clear()
        shotExecutor.shutdownNow()
        super.onDestroy()
    }

    private fun clear() {
        if (instance === this) {
            instance = null
            LinkState.notifyChanged()
            if (Config(this).paired) LinkService.start(this, LinkService.ACTION_ACCESSIBILITY_CHANGED)
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}

    override fun onInterrupt() {}

    // ---- screen state ---------------------------------------------------------------------

    fun checkUsable() {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        if (!pm.isInteractive) throw CmdError(Protocol.Err.LOCKED, "The screen is off")
        val km = getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
        if (km.isDeviceLocked) throw CmdError(Protocol.Err.LOCKED, "The phone is locked")
    }

    fun realSize(): Geometry.Size = Screen.realSize(this)

    private fun mapper(sw: Int?, sh: Int?): Geometry.Mapper {
        val real = realSize()
        val last = lastShot
        return when {
            sw != null && sh != null && sw > 0 && sh > 0 -> Geometry.Mapper(sw, sh, real.w, real.h)
            last != null -> Geometry.Mapper(last.w, last.h, real.w, real.h)
            else -> Geometry.Mapper(real.w, real.h, real.w, real.h)
        }
    }

    // ---- shot -----------------------------------------------------------------------------

    fun shot(maxW: Int?, quality: Int?): JSONObject {
        checkUsable()
        var attempt = 0
        while (true) {
            val r = takeOnce()
            if (r.bitmap != null) return encode(r.bitmap, maxW, quality)
            when (r.error) {
                ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT -> if (attempt++ < 4) {
                    SystemClock.sleep(350); continue
                }
                ERROR_TAKE_SCREENSHOT_SECURE_WINDOW_COMPAT ->
                    throw CmdError(Protocol.Err.PROTECTED, "This app protects its screen (secure window): no capture")
                ERROR_TAKE_SCREENSHOT_NO_ACCESSIBILITY_ACCESS ->
                    throw CmdError(Protocol.Err.NO_ACCESSIBILITY, "Screen capture is not allowed for the accessibility service")
                -1 -> throw CmdError(Protocol.Err.TIMEOUT, "The system did not return the screenshot")
            }
            throw CmdError(Protocol.Err.FAILED, "Screenshot failed (code ${r.error})")
        }
    }

    private class Taken(val bitmap: Bitmap?, val error: Int)

    private fun takeOnce(): Taken {
        val latch = CountDownLatch(1)
        var bmp: Bitmap? = null
        var error = -1
        takeScreenshot(Display.DEFAULT_DISPLAY, shotExecutor, object : TakeScreenshotCallback {
            override fun onSuccess(result: ScreenshotResult) {
                try {
                    val hw = Bitmap.wrapHardwareBuffer(result.hardwareBuffer, result.colorSpace)
                    bmp = hw?.copy(Bitmap.Config.ARGB_8888, false)
                    hw?.recycle()
                    if (bmp == null) error = 1
                } finally {
                    result.hardwareBuffer.close()
                    latch.countDown()
                }
            }

            override fun onFailure(errorCode: Int) {
                error = errorCode
                latch.countDown()
            }
        })
        latch.await(5, TimeUnit.SECONDS)
        return Taken(bmp, error)
    }

    private fun encode(full: Bitmap, maxW: Int?, quality: Int?): JSONObject {
        val size = Geometry.captureSize(full.width, full.height, maxW)
        val scaled = if (size.w == full.width) full else Bitmap.createScaledBitmap(full, size.w, size.h, true)
        val out = ByteArrayOutputStream(256 * 1024)
        scaled.compress(Bitmap.CompressFormat.JPEG, Geometry.quality(quality), out)
        val o = JSONObject()
            .put("jpeg", Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP))
            .put("w", size.w).put("h", size.h)
            .put("sw_screen", full.width).put("sh_screen", full.height)
        if (scaled !== full) scaled.recycle()
        full.recycle()
        lastShot = size
        return o
    }

    // ---- input ----------------------------------------------------------------------------

    fun input(f: Protocol.Frame) {
        val a = f.str("a") ?: throw CmdError(Protocol.Err.BAD_REQUEST, "missing a")
        if (a != "key") checkUsable()
        val m = mapper(f.int("sw"), f.int("sh"))
        fun px(key: String) = m.x(f.num(key) ?: throw CmdError(Protocol.Err.BAD_REQUEST, "missing $key"))
        fun py(key: String) = m.y(f.num(key) ?: throw CmdError(Protocol.Err.BAD_REQUEST, "missing $key"))
        when (a) {
            "click" -> {
                val x = px("x"); val y = py("y")
                if (f.str("button") == "right") {
                    press(x, y, 800)
                } else {
                    press(x, y, TAP_MS)
                    if (f.bool("double")) { SystemClock.sleep(90); press(x, y, TAP_MS) }
                }
            }
            "long_press" -> press(px("x"), py("y"), (f.int("ms") ?: 800).toLong().coerceIn(400, 10_000))
            "drag" -> {
                val path = Path().apply { moveTo(px("x"), py("y")); lineTo(px("x2"), py("y2")) }
                val ms = (f.int("ms") ?: 400).toLong().coerceIn(50, 10_000)
                gesture(GestureDescription.StrokeDescription(path, 0, ms))
            }
            "scroll" -> scroll(f, m)
            "type" -> type(f.str("text") ?: throw CmdError(Protocol.Err.BAD_REQUEST, "missing text"))
            "key" -> {
                val keys = f.keys()
                if (keys.isEmpty()) throw CmdError(Protocol.Err.BAD_REQUEST, "missing keys")
                keys.forEach { key(it) }
            }
            "move" -> throw CmdError(Protocol.Err.UNSUPPORTED, "A phone has no pointer: use click, long_press or drag")
            else -> throw CmdError(Protocol.Err.UNSUPPORTED, "Unknown input action: $a")
        }
    }

    private fun press(x: Float, y: Float, ms: Long) {
        val path = Path().apply { moveTo(x, y) }
        gesture(GestureDescription.StrokeDescription(path, 0, ms))
    }

    /**
     * `scroll` has mouse-wheel semantics, like on a computer: `dy > 0` shows what is further
     * down (the finger moves up), `dx > 0` what is further right. Distances in capture space.
     * The finger holds still for a moment at the end so the list does not fling past the target.
     */
    private fun scroll(f: Protocol.Frame, m: Geometry.Mapper) {
        val real = realSize()
        val x = f.num("x")?.let { m.x(it) } ?: (real.w / 2f)
        val y = f.num("y")?.let { m.y(it) } ?: (real.h / 2f)
        val dx = m.dx(f.num("dx") ?: 0.0)
        val dy = m.dy(f.num("dy") ?: 0.0)
        if (dx == 0f && dy == 0f) throw CmdError(Protocol.Err.BAD_REQUEST, "missing dx/dy")
        val ex = (x - dx).coerceIn(1f, real.w - 2f)
        val ey = (y - dy).coerceIn(1f, real.h - 2f)
        val dist = hypot((ex - x).toDouble(), (ey - y).toDouble())
        val ms = max(250.0, dist * 1.2).roundToInt().toLong().coerceAtMost(3_000)
        val move = Path().apply { moveTo(x, y); lineTo(ex, ey) }
        val first = GestureDescription.StrokeDescription(move, 0, ms, true)
        gesture(first)
        val hold = Path().apply { moveTo(ex, ey) }
        gesture(first.continueStroke(hold, 0, 120, false))
    }

    private fun gesture(stroke: GestureDescription.StrokeDescription) {
        val g = GestureDescription.Builder().addStroke(stroke).build()
        val latch = CountDownLatch(1)
        var done = false
        val sent = dispatchGesture(g, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) { done = true; latch.countDown() }
            override fun onCancelled(gestureDescription: GestureDescription?) { latch.countDown() }
        }, null)
        if (!sent) throw CmdError(Protocol.Err.FAILED, "The system refused the gesture")
        if (!latch.await(stroke.duration + 5_000, TimeUnit.MILLISECONDS)) {
            throw CmdError(Protocol.Err.TIMEOUT, "The gesture did not finish")
        }
        if (!done) throw CmdError(Protocol.Err.FAILED, "The gesture was cancelled (the screen changed or the user touched it)")
    }

    // ---- text -----------------------------------------------------------------------------

    private fun focusedField(): AccessibilityNodeInfo {
        val n = findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
        if (n == null || !n.isEditable) throw CmdError(Protocol.Err.NO_FOCUS, "No text field has the focus: tap one first")
        return n
    }

    /**
     * `type`: inserts the text at the cursor of the focused field (replacing the selection),
     * at the end when the field gives no cursor. Password fields are filled whole (their
     * current text cannot be read).
     */
    fun type(text: String) {
        val n = focusedField()
        val r = if (n.isPassword) TextEdit.Result(text, text.length)
        else TextEdit.insert(n.text, n.isShowingHintText, n.textSelectionStart, n.textSelectionEnd, text)
        setTextOn(n, r)
    }

    private fun setTextOn(n: AccessibilityNodeInfo, r: TextEdit.Result) {
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, r.text)
        }
        if (!n.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
            throw CmdError(Protocol.Err.FAILED, "The field refused the text")
        }
        val sel = Bundle().apply {
            putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, r.cursor)
            putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, r.cursor)
        }
        n.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION, sel)
    }

    fun key(name: String) {
        when (val k = Keys.map(name)) {
            is KeyAction.Global -> if (!performGlobalAction(k.action)) {
                throw CmdError(Protocol.Err.FAILED, "The system refused the key $name")
            }
            KeyAction.Enter -> {
                checkUsable()
                val n = focusedField()
                if (!n.performAction(AccessibilityAction.ACTION_IME_ENTER.id)) {
                    throw CmdError(Protocol.Err.FAILED, "The field has no enter action")
                }
            }
            KeyAction.Backspace -> {
                checkUsable()
                val n = focusedField()
                val r = if (n.isPassword) TextEdit.Result("", 0)
                else TextEdit.backspace(n.text, n.isShowingHintText, n.textSelectionStart, n.textSelectionEnd)
                setTextOn(n, r)
            }
            is KeyAction.Unsupported -> throw CmdError(
                Protocol.Err.UNSUPPORTED, "Key not available on Android: ${k.name} (keys: ${Keys.SUPPORTED})"
            )
        }
    }

    // ---- tree -----------------------------------------------------------------------------

    fun tree(sw: Int?, sh: Int?): JSONObject {
        checkUsable()
        val m = mapper(sw, sh)
        val cap = if (sw != null && sh != null && sw > 0 && sh > 0) Geometry.Size(sw, sh)
        else lastShot ?: realSize()
        val out = JSONArray()
        val keep = HashMap<Int, AccessibilityNodeInfo>()
        var truncated = false
        val rect = Rect()
        val wins = try { windows.sortedByDescending { it.layer } } catch (_: Exception) { emptyList() }
        val roots = wins.mapNotNull { it.root }.ifEmpty { listOfNotNull(rootInActiveWindow) }
        val app = rootInActiveWindow?.packageName?.toString()
        val stack = ArrayDeque<AccessibilityNodeInfo>()
        for (root in roots) {
            stack.clear(); stack.addLast(root)
            while (stack.isNotEmpty()) {
                val n = stack.removeLast()
                if (!n.isVisibleToUser) continue
                for (i in n.childCount - 1 downTo 0) n.getChild(i)?.let { stack.addLast(it) }
                val text = n.text?.toString()?.trim().orEmpty()
                val desc = n.contentDescription?.toString()?.trim().orEmpty()
                val useful = text.isNotEmpty() || desc.isNotEmpty() || n.isClickable || n.isLongClickable ||
                    n.isEditable || n.isScrollable || n.isCheckable
                if (!useful) continue
                n.getBoundsInScreen(rect)
                if (rect.width() <= 0 || rect.height() <= 0) continue
                if (keep.size >= MAX_NODES) { truncated = true; break }
                val id = keep.size + 1
                keep[id] = n
                val o = JSONObject()
                    .put("id", id)
                    .put("role", n.className?.toString()?.substringAfterLast('.') ?: "View")
                    .put("text", text.take(300))
                    .put("desc", desc.take(300))
                    .put("b", JSONArray(m.box(rect.left, rect.top, rect.right, rect.bottom).toList()))
                    .put("click", n.isClickable || n.isLongClickable)
                    .put("edit", n.isEditable)
                    .put("focus", n.isFocused || n.isAccessibilityFocused)
                if (n.isScrollable) o.put("scroll", true)
                if (n.isCheckable) o.put("checked", n.isChecked)
                if (n.isPassword) o.put("password", true)
                n.viewIdResourceName?.let { o.put("rid", it.substringAfter(":id/")) }
                out.put(o)
            }
            if (truncated) break
        }
        lastNodes = keep
        val r = JSONObject().put("nodes", out).put("sw", cap.w).put("sh", cap.h)
        if (app != null) r.put("app", app)
        if (truncated) r.put("truncated", true)
        return r
    }

    private fun node(id: Int?): AccessibilityNodeInfo {
        val n = lastNodes[id ?: throw CmdError(Protocol.Err.BAD_REQUEST, "missing node")]
            ?: throw CmdError(Protocol.Err.STALE, "Unknown node $id: ask for a new tree")
        if (!n.refresh() || !n.isVisibleToUser) throw CmdError(Protocol.Err.STALE, "Node $id is gone: ask for a new tree")
        return n
    }

    fun tapNode(id: Int?) {
        checkUsable()
        val n = node(id)
        var c: AccessibilityNodeInfo? = n
        while (c != null && !c.isClickable) c = c.parent
        if (c != null && c.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return
        val r = Rect().also { n.getBoundsInScreen(it) }
        press(r.exactCenterX(), r.exactCenterY(), TAP_MS)
    }

    fun setText(id: Int?, text: String) {
        checkUsable()
        val n = node(id)
        if (!n.isEditable) throw CmdError(Protocol.Err.BAD_REQUEST, "Node $id is not a text field")
        if (!n.isFocused) n.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        setTextOn(n, TextEdit.Result(text, text.length))
    }

    // ---- apps -----------------------------------------------------------------------------

    fun open(app: String) {
        checkUsable()
        val intent = Apps.launchIntent(this, app)
            ?: throw CmdError(Protocol.Err.NOT_FOUND, "No app \"$app\": use apps for the list")
        try {
            startActivity(intent)
        } catch (e: Exception) {
            throw CmdError(Protocol.Err.FAILED, "Could not open $app: ${e.javaClass.simpleName}")
        }
    }

    companion object {
        const val MAX_NODES = 400
        private const val TAP_MS = 60L
        // ERROR_TAKE_SCREENSHOT_SECURE_WINDOW is public since API 34; same value on 30-33.
        private const val ERROR_TAKE_SCREENSHOT_SECURE_WINDOW_COMPAT = 5

        @Volatile var instance: LinkAccessibilityService? = null
            private set

        val enabled: Boolean get() = instance != null
    }
}

/** Launcher apps (the manifest only declares a `<queries>` for MAIN/LAUNCHER). */
object Apps {
    data class App(val id: String, val name: String)

    fun list(context: Context): List<App> {
        val pm = context.packageManager
        val i = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val found = if (Build.VERSION.SDK_INT >= 33) {
            pm.queryIntentActivities(i, PackageManager.ResolveInfoFlags.of(0))
        } else {
            @Suppress("DEPRECATION") pm.queryIntentActivities(i, 0)
        }
        return found.map { App(it.activityInfo.packageName, it.loadLabel(pm).toString()) }
            .distinctBy { it.id }
            .sortedBy { it.name.lowercase() }
    }

    /** `app` = a package id from `apps`, or a name ("Settings", "whatsapp"). */
    fun launchIntent(context: Context, app: String): Intent? {
        val pm = context.packageManager
        val wanted = app.trim()
        if (wanted.isEmpty()) return null
        val pkg = pm.getLaunchIntentForPackage(wanted)?.let { wanted } ?: run {
            val all = list(context)
            val w = wanted.lowercase()
            (all.firstOrNull { it.name.lowercase() == w }
                ?: all.firstOrNull { it.name.lowercase().startsWith(w) }
                ?: all.firstOrNull { it.name.lowercase().contains(w) })?.id
        } ?: return null
        return pm.getLaunchIntentForPackage(pkg)?.addFlags(
            Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED
        )
    }
}
