package com.harnessmaxxing.link

import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Coordinates sent by the server are in "capture space": the pixels of the last screenshot
 * it received (`sw` x `sh`, usually downscaled). The phone converts them to real display pixels.
 */
object Geometry {
    const val DEFAULT_MAX_W = 1280
    const val DEFAULT_QUALITY = 70

    data class Size(val w: Int, val h: Int)

    /** Size of a capture of a `realW` x `realH` screen, at most `maxW` wide (never upscaled). */
    fun captureSize(realW: Int, realH: Int, maxW: Int?): Size {
        val limit = when {
            maxW == null || maxW <= 0 -> DEFAULT_MAX_W
            else -> maxW.coerceIn(160, 4096)
        }
        if (realW <= limit) return Size(realW, realH)
        return Size(limit, max(1, (realH.toDouble() * limit / realW).roundToInt()))
    }

    fun quality(q: Int?): Int = if (q == null || q <= 0) DEFAULT_QUALITY else q.coerceIn(10, 95)

    /** Maps a point of capture space (`sw` x `sh`) to the real display (`realW` x `realH`). */
    class Mapper(sw: Int, sh: Int, private val realW: Int, private val realH: Int) {
        private val fromW = if (sw > 0) sw else realW
        private val fromH = if (sh > 0) sh else realH

        fun x(v: Double): Float = clamp(v * realW / fromW, realW)
        fun y(v: Double): Float = clamp(v * realH / fromH, realH)
        fun dx(v: Double): Float = (v * realW / fromW).toFloat()
        fun dy(v: Double): Float = (v * realH / fromH).toFloat()

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
