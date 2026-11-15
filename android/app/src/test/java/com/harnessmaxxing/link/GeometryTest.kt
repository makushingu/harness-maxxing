package com.harnessmaxxing.link

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class GeometryTest {
    @Test fun captureIsDownscaledToMaxWidthKeepingTheRatio() {
        assertEquals(Geometry.Size(1280, 2773), Geometry.captureSize(1440, 3120, null))
        assertEquals(Geometry.Size(720, 1560), Geometry.captureSize(1440, 3120, 720))
        assertEquals(Geometry.Size(1080, 2400), Geometry.captureSize(1080, 2400, 1280)) // never upscaled
        assertEquals(Geometry.Size(1280, 2773), Geometry.captureSize(1440, 3120, 0))
        assertEquals(Geometry.Size(160, 347), Geometry.captureSize(1440, 3120, 10))  // floor
    }

    @Test fun quality() {
        assertEquals(70, Geometry.quality(null))
        assertEquals(95, Geometry.quality(100))
        assertEquals(10, Geometry.quality(3))
        assertEquals(55, Geometry.quality(55))
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
