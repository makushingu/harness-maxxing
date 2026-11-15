package com.harnessmaxxing.link

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class GeometryTest {
    @Test fun captureIsDownscaledToMaxWidthKeepingTheRatio() {
        assertEquals(Geometry.Size(1280, 2773), Geometry.captureSize(1440, 3120, 1280))
        assertEquals(Geometry.Size(720, 1560), Geometry.captureSize(1440, 3120, 720))
        assertEquals(Geometry.Size(1080, 2400), Geometry.captureSize(1080, 2400, 1280)) // never enlarged
        assertEquals(Geometry.Size(1440, 3120), Geometry.captureSize(1440, 3120, 0))   // 0 = full size
        assertEquals(Geometry.Size(1440, 3120), Geometry.captureSize(1440, 3120, null))
    }

    @Test fun quality() {
        assertEquals(70, Geometry.quality(null))
        assertEquals(95, Geometry.quality(100))
        assertEquals(20, Geometry.quality(3))
        assertEquals(55, Geometry.quality(55))
    }

    @Test fun cropIsInCaptureSpaceAndCutToTheScreen() {
        // A 540 x 1170 capture of a 1080 x 2340 screen.
        assertArrayEquals(intArrayOf(200, 400, 100, 60), Geometry.crop(100.0, 200.0, 50.0, 30.0, 540, 1170, 1080, 2340))
        assertArrayEquals(intArrayOf(1000, 0, 80, 20), Geometry.crop(500.0, -5.0, 100.0, 15.0, 540, 1170, 1080, 2340))
        assertNull(Geometry.crop(600.0, 10.0, 50.0, 50.0, 540, 1170, 1080, 2340)) // outside
        assertNull(Geometry.crop(10.0, 10.0, 0.0, 50.0, 540, 1170, 1080, 2340))
        assertArrayEquals(intArrayOf(10, 10, 5, 5), Geometry.crop(10.0, 10.0, 5.0, 5.0, 0, 0, 1080, 2340)) // no sw/sh
    }

    @Test fun wheelNotches() {
        assertEquals(0, Geometry.notches(null))
        assertEquals(0, Geometry.notches(0.0))
        assertEquals(1, Geometry.notches(0.2))   // non-zero = at least one
        assertEquals(-1, Geometry.notches(-0.4))
        assertEquals(3, Geometry.notches(2.6))
        assertEquals(100, Geometry.notches(5000.0))
        assertEquals(-100, Geometry.notches(-5000.0))
    }

    @Test fun captureToRealAndBack() {
        val m = Geometry.Mapper(720, 1560, 1440, 3120)
        assertEquals(200f, m.x(100.0), 0.001f)
        assertEquals(3000f, m.y(1500.0), 0.001f)
        assertEquals(1439f, m.x(5000.0), 0.001f) // clamped on screen
        assertEquals(0f, m.y(-5.0), 0.001f)
        assertEquals(-100f, m.dy(-50.0), 0.001f) // distances are not clamped
        assertArrayEquals(intArrayOf(50, 100, 25, 50), m.box(100, 200, 150, 300))
        assertArrayEquals(intArrayOf(0, 0, 720, 10), m.box(-10, -10, 9999, 20))
    }

    @Test fun missingCaptureSizeMeansRealPixels() {
        val m = Geometry.Mapper(0, 0, 1080, 2400)
        assertEquals(500f, m.x(500.0), 0.001f)
    }
}
