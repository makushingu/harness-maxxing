package com.harnessmaxxing.link

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

class BackoffTest {
    @Test fun doublesFromOneSecondUpToSixtyWithJitter() {
        val b = Backoff(random = Random(7))
        val bases = listOf(1_000L, 2_000, 4_000, 8_000, 16_000, 32_000, 60_000, 60_000, 60_000)
        for (base in bases) {
            val d = b.next()
            assertTrue("$d for $base", d >= base && d <= base + base / 5)
        }
    }

    @Test fun resetStartsOver() {
        val b = Backoff(random = Random(1))
        repeat(10) { b.next() }
        b.reset()
        assertTrue(b.next() <= 1_200)
    }

    @Test fun noJitterSource() {
        val zero = object : Random() { override fun nextBits(bitCount: Int) = 0 }
        val b = Backoff(random = zero)
        assertEquals(1_000L, b.next())
        assertEquals(2_000L, b.next())
    }
}
