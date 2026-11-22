package com.harnessmaxxing.link

import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Coordinates sent by the server are in "capture space": the pixels of the last screenshot
 * it received (`sw` x `sh`, usually downscaled). The phone converts them to real display pixels.
 */
object Geometry {
    const val DEFAULT_QUALITY = 70

    data class Size(val w: Int, val h: Int)

    /** Size of a capture of `realW` x `realH`, at most `maxW` wide (0 / absent = full size, never enlarged). */
    fun captureSize(realW: Int, realH: Int, maxW: Int?): Size {
        if (maxW == null || maxW <= 0 || realW <= maxW) return Size(realW, realH)
        val limit = maxW.coerceAtLeast(16)
        return Size(limit, max(1, (realH.toDouble() * limit / realW).roundToInt()))
    }

    fun quality(q: Int?): Int = if (q == null || q <= 0) DEFAULT_QUALITY else q.coerceIn(20, 95)

    /**
     * Zoom: `x,y,w,h` in capture space (`sw` x `sh`) -> real pixels `[left, top, width, height]`, cut to
     * the screen. Null when the rectangle is empty or entirely outside the screen.
     */
    fun crop(x: Double, y: Double, w: Double, h: Double, sw: Int, sh: Int, realW: Int, realH: Int): IntArray? {
        if (w <= 0 || h <= 0) return null
        val fx = if (sw > 0) realW.toDouble() / sw else 1.0
        val fy = if (sh > 0) realH.toDouble() / sh else 1.0
        val l = max(0, (x * fx).roundToInt())
        val t = max(0, (y * fy).roundToInt())
        val r = min(realW, ((x + w) * fx).roundToInt())
        val b = min(realH, ((y + h) * fy).roundToInt())
        if (r - l < 1 || b - t < 1) return null
        return intArrayOf(l, t, r - l, b - t)
    }

    /** Wheel notches: rounded, a non-zero value is at least 1, at most 100 (either sign). */
    fun notches(v: Double?): Int {
        if (v == null || v == 0.0 || v.isNaN()) return 0
        val n = v.roundToInt().coerceIn(-100, 100)
        return if (n == 0) (if (v > 0) 1 else -1) else n
    }

    /** Maps a point of capture space (`sw` x `sh`) to the real display (`realW` x `realH`). */
    class Mapper(sw: Int, sh: Int, private val realW: Int, private val realH: Int) {
        private val fromW = if (sw > 0) sw else realW
        private val fromH = if (sh > 0) sh else realH

        fun x(v: Double): Float = clamp(v * realW / fromW, realW)
        fun y(v: Double): Float = clamp(v * realH / fromH, realH)

        /** Real rectangle (left, top, right, bottom) -> `[x, y, w, h]` in capture space. */
        fun box(left: Int, top: Int, right: Int, bottom: Int): IntArray {
            val sx = fromW.toDouble() / realW
            val sy = fromH.toDouble() / realH
            val l = (max(0, left) * sx).roundToInt()
            val t = (max(0, top) * sy).roundToInt()
            val r = (min(realW, right) * sx).roundToInt()
            val b = (min(realH, bottom) * sy).roundToInt()
            return intArrayOf(l, t, max(0, r - l), max(0, b - t))
        }

        private fun clamp(v: Double, limit: Int): Float =
            v.coerceIn(0.0, (limit - 1).toDouble()).toFloat()
    }
}
