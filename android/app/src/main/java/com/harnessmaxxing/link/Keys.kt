package com.harnessmaxxing.link

/** What one key combo of `input` `key` becomes on Android. */
sealed class KeyAction {
    /** `AccessibilityService.performGlobalAction(action)`. */
    data class Global(val action: Int) : KeyAction()
    /** The IME action of the focused field (send, search, go...): ACTION_IME_ENTER. */
    data object Enter : KeyAction()
    /** Delete the selection or the character before the cursor of the focused field. */
    data object Backspace : KeyAction()
    /** Delete the selection or the character after the cursor. */
    data object Delete : KeyAction()
    data object SelectAll : KeyAction()
    data object Copy : KeyAction()
    data object Cut : KeyAction()
    data object Paste : KeyAction()
    /** A single character (or space) inserted in the focused field. */
    data class Text(val text: String) : KeyAction()
    /** A valid key name that a phone cannot press (`ctrl+s`, `f5`, `tab`...): `unsupported`. */
    data class Unsupported(val combo: String) : KeyAction()
    /** Not a key name, or several keys in one combo: `bad_request`. */
    data class Bad(val combo: String) : KeyAction()
}

/**
 * Key names of link/PROTOCOL.md: combos `mod+mod+key`, modifiers first. On Android `back`, `home`
 * (home screen) and `recents` are system keys; `esc` = back.
 */
object Keys {
    // Values of AccessibilityService.GLOBAL_ACTION_* (stable since API 16-28).
    const val GLOBAL_BACK = 1
    const val GLOBAL_HOME = 2
    const val GLOBAL_RECENTS = 3
    const val GLOBAL_NOTIFICATIONS = 4
    const val GLOBAL_QUICK_SETTINGS = 5
    const val GLOBAL_POWER_DIALOG = 6
    const val GLOBAL_LOCK_SCREEN = 8

    const val SUPPORTED = "back, home, recents, notifications, quick_settings, enter, backspace, delete, space, " +
        "esc, one character, ctrl+a / ctrl+c / ctrl+x / ctrl+v"

    private val MODIFIERS = mapOf(
        "ctrl" to "ctrl", "control" to "ctrl", "cmd" to "ctrl", "command" to "ctrl", "meta" to "ctrl",
        "win" to "win", "super" to "win", "shift" to "shift", "alt" to "alt", "option" to "alt",
    )

    /** Desktop keys that exist in the protocol but have no meaning on a phone. */
    private val DESKTOP_ONLY = setOf(
        "tab", "insert", "end", "pageup", "pagedown", "left", "up", "right", "down", "capslock",
        "printscreen", "menu",
    ) + (1..24).map { "f$it" }

    fun map(combo: String): KeyAction {
        val raw = combo.trim()
        if (raw.isEmpty()) return KeyAction.Bad(combo)
        val parts: List<String> = when {
            raw == "+" -> listOf("+")
            raw.endsWith("++") -> raw.dropLast(2).split('+').filter { it.isNotEmpty() } + "+"
            else -> raw.split('+')
        }
        if (parts.any { it.isEmpty() }) return KeyAction.Bad(combo)
        val mods = mutableSetOf<String>()
        var key: String? = null
        for (p in parts) {
            val l = p.lowercase()
            val m = MODIFIERS[l]
            when {
                m != null && key == null -> mods += m
                key != null -> return KeyAction.Bad(combo) // modifiers first, then at most one key
                else -> key = if (l == "plus") "+" else p
            }
        }
        val k = key ?: return KeyAction.Unsupported(combo) // modifiers alone
        val lk = k.lowercase().replace('-', '_')
        if (mods.isNotEmpty()) {
            if (mods == setOf("ctrl")) when (lk) {
                "a" -> return KeyAction.SelectAll
                "c" -> return KeyAction.Copy
                "x" -> return KeyAction.Cut
                "v" -> return KeyAction.Paste
            }
            if (mods == setOf("shift") && k.codePointCount(0, k.length) == 1) return KeyAction.Text(k.uppercase())
            return if (isKeyName(lk) || k.codePointCount(0, k.length) == 1) KeyAction.Unsupported(combo) else KeyAction.Bad(combo)
        }
        return when (lk) {
            "back", "esc", "escape" -> KeyAction.Global(GLOBAL_BACK)
            "home" -> KeyAction.Global(GLOBAL_HOME)
            "recents", "recent_apps", "overview", "app_switch" -> KeyAction.Global(GLOBAL_RECENTS)
            "notifications" -> KeyAction.Global(GLOBAL_NOTIFICATIONS)
            "quick_settings" -> KeyAction.Global(GLOBAL_QUICK_SETTINGS)
            "power" -> KeyAction.Global(GLOBAL_POWER_DIALOG)
            "lock", "lock_screen" -> KeyAction.Global(GLOBAL_LOCK_SCREEN)
            "enter", "return" -> KeyAction.Enter
            "backspace" -> KeyAction.Backspace
            "delete", "del" -> KeyAction.Delete
            "space" -> KeyAction.Text(" ")
            in DESKTOP_ONLY -> KeyAction.Unsupported(combo)
            else -> if (k.codePointCount(0, k.length) == 1) KeyAction.Text(k) else KeyAction.Bad(combo)
        }
    }

    private fun isKeyName(lk: String) = lk in DESKTOP_ONLY || lk in setOf(
        "back", "esc", "escape", "home", "recents", "enter", "return", "backspace", "delete", "space",
    )
}
