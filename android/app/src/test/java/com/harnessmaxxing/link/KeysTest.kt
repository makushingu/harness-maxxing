package com.harnessmaxxing.link

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class KeysTest {
    @Test fun globalKeysMatchAndroidConstants() {
        // Values of android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_*.
        assertEquals(KeyAction.Global(1), Keys.map("back"))
        assertEquals(KeyAction.Global(1), Keys.map("Escape"))
        assertEquals(KeyAction.Global(2), Keys.map("HOME"))
        assertEquals(KeyAction.Global(3), Keys.map("recents"))
        assertEquals(KeyAction.Global(3), Keys.map("app switch"))
        assertEquals(KeyAction.Global(4), Keys.map("notifications"))
        assertEquals(KeyAction.Global(5), Keys.map("quick-settings"))
        assertEquals(KeyAction.Global(8), Keys.map("lock"))
    }

    @Test fun enterAndBackspace() {
        assertEquals(KeyAction.Enter, Keys.map("enter"))
        assertEquals(KeyAction.Enter, Keys.map(" Return "))
        assertEquals(KeyAction.Backspace, Keys.map("backspace"))
    }

    @Test fun desktopShortcutsAreUnsupported() {
        assertTrue(Keys.map("ctrl+s") is KeyAction.Unsupported)
        assertTrue(Keys.map("f5") is KeyAction.Unsupported)
    }
}
