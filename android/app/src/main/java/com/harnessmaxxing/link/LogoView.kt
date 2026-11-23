package com.harnessmaxxing.link

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.util.AttributeSet
import android.view.View
import kotlin.math.min
import kotlin.math.roundToInt

private fun round(v: Float) = v.roundToInt().toFloat()

/**
 * "LINK" in the big terminal letters of the desktop app and the installer (same art, same blues top to bottom),
 * drawn cell by cell instead of with a font: the phone's monospace font has no reliable box-drawing glyphs,
 * and the art always fits the width, never cut nor wrapped, on any screen.
 */
class LogoView @JvmOverloads constructor(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {

    private val rows = LOGO.size
    private val cols = LOGO.maxOf { it.length }
    private val fill = Paint().apply { style = Paint.Style.FILL }
    private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeCap = Paint.Cap.SQUARE }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val w = MeasureSpec.getSize(widthMeasureSpec)
        // A terminal cell is about twice as tall as wide; capped so a tablet does not get a giant logo.
        val cell = min((w - paddingLeft - paddingRight).toFloat() / cols, MAX_CELL_DP * resources.displayMetrics.density)
        val h = (cell * CELL_RATIO * rows).toInt() + paddingTop + paddingBottom
        setMeasuredDimension(w, resolveSize(h, heightMeasureSpec))
    }

    override fun onDraw(canvas: Canvas) {
        val cw = min((width - paddingLeft - paddingRight).toFloat() / cols, (height - paddingTop - paddingBottom).toFloat() / (rows * CELL_RATIO))
        val ch = cw * CELL_RATIO
        val x0 = paddingLeft + ((width - paddingLeft - paddingRight) - cw * cols) / 2
        val y0 = paddingTop + ((height - paddingTop - paddingBottom) - ch * rows) / 2
        line.strokeWidth = maxOf(1f, cw * 0.12f)
        val gap = cw * 0.17f // half the distance between the two strokes of a double line
        for ((r, text) in LOGO.withIndex()) {
            fill.color = BLUES[r]
            line.color = BLUES[r]
            line.alpha = 150
            for ((c, ch0) in text.withIndex()) {
                if (ch0 == ' ') continue
                // Cell edges snapped to whole pixels: neighbouring blocks touch without a hairline between them.
                val l = round(x0 + c * cw)
                val rr = round(x0 + (c + 1) * cw)
                val t = round(y0 + r * ch)
                val b = round(y0 + (r + 1) * ch)
                if (ch0 == '█') { canvas.drawRect(l, t, rr, b, fill); continue }
                val cx = (l + rr) / 2
                val cy = (t + b) / 2
                val (left, right, up, down) = arms(ch0)
                // Double lines: o = -gap is the stroke on the top / left, o = +gap the one on the bottom / right.
                for (o in floatArrayOf(-gap, gap)) {
                    if (left || right) {
                        val y = cy + o
                        val sx = if (left) l else cx + (if (down) o else -o)
                        val ex = if (right) rr else cx + (if (down) -o else o)
                        canvas.drawLine(sx, y, ex, y, line)
                    }
                    if (up || down) {
                        val x = cx + o
                        val sy = if (up) t else cy + (if (left) -o else o)
                        val ey = if (down) b else cy + (if (left) o else -o)
                        canvas.drawLine(x, sy, x, ey, line)
                    }
                }
            }
        }
    }

    private data class Arms(val left: Boolean, val right: Boolean, val up: Boolean, val down: Boolean)

    private fun arms(c: Char) = when (c) {
        '═' -> Arms(left = true, right = true, up = false, down = false)
        '║' -> Arms(left = false, right = false, up = true, down = true)
        '╗' -> Arms(left = true, right = false, up = false, down = true)
        '╔' -> Arms(left = false, right = true, up = false, down = true)
        '╝' -> Arms(left = true, right = false, up = true, down = false)
        '╚' -> Arms(left = false, right = true, up = true, down = false)
        else -> Arms(left = false, right = false, up = false, down = false)
    }

    companion object {
        private const val CELL_RATIO = 1.8f
        private const val MAX_CELL_DP = 14f

        // Same art as link/console.go.
        val LOGO = arrayOf(
            "██╗     ██╗███╗   ██╗██╗  ██╗",
            "██║     ██║████╗  ██║██║ ██╔╝",
            "██║     ██║██╔██╗ ██║█████╔╝ ",
            "██║     ██║██║╚██╗██║██╔═██╗ ",
            "███████╗██║██║ ╚████║██║  ██╗",
            "╚══════╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝",
        )

        // xterm-256 colours 27, 33, 39, 45, 51, 87 (the desktop app and the installer).
        private val BLUES = intArrayOf(
            0xFF005FFF.toInt(), 0xFF0087FF.toInt(), 0xFF00AFFF.toInt(),
            0xFF00D7FF.toInt(), 0xFF00FFFF.toInt(), 0xFF5FFFFF.toInt(),
        )
    }
}
