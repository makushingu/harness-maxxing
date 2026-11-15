package com.harnessmaxxing.link

import kotlin.random.Random

/** Reconnection delays: 1 s, 2 s, 4 s ... up to 60 s, plus up to 20 % of random jitter. */
class Backoff(
    private val baseMs: Long = 1_000,
    private val capMs: Long = 60_000,
    private val random: Random = Random.Default,
) {
    private var attempt = 0

    fun next(): Long {
        val shift = attempt.coerceAtMost(16)
        val d = (baseMs shl shift).coerceAtMost(capMs)
        attempt++
        val jitter = if (d >= 4) random.nextLong(0, d / 5 + 1) else 0
        return d + jitter
    }

    fun reset() {
        attempt = 0
    }
}
