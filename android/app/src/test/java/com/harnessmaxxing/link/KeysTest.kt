package com.harnessmaxxing.link

import org.junit.Assert.assertEquals
import org.junit.Test

class KeysTest {
    @Test fun systemKeysMatchAndroidConstants() {
        // Values of android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_*.
        assertEquals(KeyAction.Global(1), Keys.map("back"))
        assertEquals(KeyAction.Global(1), Keys.map("Esc"))
        assertEquals(KeyAction.Global(2), Keys.map("HOME"))
        assertEquals(KeyAction.Global(3), Keys.map("recents"))
        assertEquals(KeyAction.Global(4), Keys.map("notifications"))
        assertEquals(KeyAction.Global(5), Keys.map("quick-settings"))
        assertEquals(KeyAction.Global(8), Keys.map("lock"))
    }

    @Test fun editingKeys() {
        assertEquals(KeyAction.Enter, Keys.map("enter"))
        assertEquals(KeyAction.Enter, Keys.map("Return"))
        assertEquals(KeyAction.Backspace, Keys.map("backspace"))
        assertEquals(KeyAction.Delete, Keys.map("delete"))
        assertEquals(KeyAction.Text(" "), Keys.map("space"))
        assertEquals(KeyAction.Text("é"), Keys.map("é"))
        assertEquals(KeyAction.Text("+"), Keys.map("plus"))
        assertEquals(KeyAction.Text("+"), Keys.map("+"))
        assertEquals(KeyAction.Text("A"), Keys.map("shift+a"))
    }

    @Test fun clipboardCombos() {
        assertEquals(KeyAction.SelectAll, Keys.map("ctrl+a"))
        assertEquals(KeyAction.SelectAll, Keys.map("cmd+A"))
        assertEquals(KeyAction.Copy, Keys.map("ctrl+c"))
        assertEquals(KeyAction.Cut, Keys.map("ctrl+x"))
        assertEquals(KeyAction.Paste, Keys.map("Control+v"))
    }

    @Test fun validDesktopKeysAreUnsupported() {
        assertEquals(KeyAction.Unsupported("ctrl+s"), Keys.map("ctrl+s"))
        assertEquals(KeyAction.Unsupported("alt+tab"), Keys.map("alt+tab"))
        assertEquals(KeyAction.Unsupported("f5"), Keys.map("f5"))
        assertEquals(KeyAction.Unsupported("tab"), Keys.map("tab"))
        assertEquals(KeyAction.Unsupported("ctrl++"), Keys.map("ctrl++"))
        assertEquals(KeyAction.Unsupported("shift"), Keys.map("shift"))
    }

    @Test fun unknownNamesAndBadCombosAreBadRequests() {
        assertEquals(KeyAction.Bad("frobnicate"), Keys.map("frobnicate"))
        assertEquals(KeyAction.Bad("a+b"), Keys.map("a+b"))
        assertEquals(KeyAction.Bad("ctrl+"), Keys.map("ctrl+"))
        assertEquals(KeyAction.Bad(""), Keys.map(""))
    }
}
