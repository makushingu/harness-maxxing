package com.harnessmaxxing.link

import org.junit.Assert.assertEquals
import org.junit.Test

class TextEditTest {
    @Test fun insertsAtTheCursor() {
        assertEquals(TextEdit.Result("hello big world", 10), TextEdit.insert("hello world", false, 6, 6, "big "))
    }

    @Test fun replacesTheSelection() {
        assertEquals(TextEdit.Result("hello there", 11), TextEdit.insert("hello world", false, 6, 11, "there"))
        assertEquals(TextEdit.Result("hello there", 11), TextEdit.insert("hello world", false, 11, 6, "there"))
    }

    @Test fun appendsWhenTheCursorIsUnknown() {
        assertEquals(TextEdit.Result("abcdef", 6), TextEdit.insert("abc", false, -1, -1, "def"))
        assertEquals(TextEdit.Result("abcdef", 6), TextEdit.insert("abc", false, 9, 9, "def"))
    }

    @Test fun hintIsNotText() {
        assertEquals(TextEdit.Result("Paris", 5), TextEdit.insert("Search", true, 0, 0, "Paris"))
        assertEquals(TextEdit.Result("x", 1), TextEdit.insert(null, false, 0, 0, "x"))
    }

    @Test fun backspace() {
        assertEquals(TextEdit.Result("helo", 3), TextEdit.backspace("hello", false, 4, 4))
        assertEquals(TextEdit.Result("hell", 4), TextEdit.backspace("hello", false, -1, -1))
        assertEquals(TextEdit.Result("ho", 1), TextEdit.backspace("hello", false, 1, 4))
        assertEquals(TextEdit.Result("abc", 0), TextEdit.backspace("abc", false, 0, 0))
        assertEquals(TextEdit.Result("a", 1), TextEdit.backspace("a😀", false, 3, 3)) // emoji = 2 chars
    }

    @Test fun deleteForward() {
        assertEquals(TextEdit.Result("helo", 3), TextEdit.deleteForward("hello", false, 3, 3))
        assertEquals(TextEdit.Result("hello", 5), TextEdit.deleteForward("hello", false, 5, 5))
        assertEquals(TextEdit.Result("ho", 1), TextEdit.deleteForward("hello", false, 1, 4))
        assertEquals(TextEdit.Result("a", 1), TextEdit.deleteForward("a😀", false, 1, 1))
    }
}
