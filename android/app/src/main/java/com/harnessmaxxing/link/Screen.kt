package com.harnessmaxxing.link

import android.content.Context
import android.graphics.Point
import android.hardware.display.DisplayManager
import android.view.Display

/** Real size of the default display in pixels, in its current rotation. */
object Screen {
    fun realSize(context: Context): Geometry.Size {
        val d = context.getSystemService(DisplayManager::class.java).getDisplay(Display.DEFAULT_DISPLAY)
        val p = Point()
        @Suppress("DEPRECATION")
        d.getRealSize(p)
        return Geometry.Size(p.x, p.y)
    }

    fun density(context: Context): Double = context.resources.displayMetrics.density.toDouble()
}

/** A refused command: becomes `{"t":"err","code":code,"message":message}`. */
class CmdError(val code: String, message: String) : Exception(message)
