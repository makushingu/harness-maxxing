package com.harnessmaxxing.link

/**
 * Text editing done with ACTION_SET_TEXT (the accessibility API cannot type keys):
 * `type` inserts at the cursor, replacing the selection; at the end when the cursor is unknown.
 */
object TextEdit {
    data class Result(val text: String, val cursor: Int)

    fun insert(current: CharSequence?, showingHint: Boolean, selStart: Int, selEnd: Int, input: String): Result {
        val text = plain(current, showingHint)
        val (s, e) = range(text, selStart, selEnd)
        val out = text.substring(0, s) + input + text.substring(e)
        return Result(out, s + input.length)
    }

    fun backspace(current: CharSequence?, showingHint: Boolean, selStart: Int, selEnd: Int): Result {
        val text = plain(current, showingHint)
        var (s, e) = range(text, selStart, selEnd)
        if (s == e) {
            if (s == 0) return Result(text, 0)
            s -= 1
            if (s > 0 && Character.isLowSurrogate(text[s]) && Character.isHighSurrogate(text[s - 1])) s -= 1
        }
        return Result(text.substring(0, s) + text.substring(e), s)
    }

    fun deleteForward(current: CharSequence?, showingHint: Boolean, selStart: Int, selEnd: Int): Result {
        val text = plain(current, showingHint)
        val (s, e0) = range(text, selStart, selEnd)
        var e = e0
        if (s == e) {
            if (e >= text.length) return Result(text, s)
            e += 1
            if (e < text.length && Character.isHighSurrogate(text[e - 1]) && Character.isLowSurrogate(text[e])) e += 1
        }
        return Result(text.substring(0, s) + text.substring(e), s)
    }

    /** The text of the field ("" while it shows its hint). */
    private fun plain(current: CharSequence?, showingHint: Boolean) =
        if (current == null || showingHint) "" else current.toString()

    private fun range(text: String, selStart: Int, selEnd: Int): Pair<Int, Int> {
        if (selStart < 0 || selEnd < 0 || selStart > text.length || selEnd > text.length) {
            return text.length to text.length
        }
        return minOf(selStart, selEnd) to maxOf(selStart, selEnd)
    }
}
