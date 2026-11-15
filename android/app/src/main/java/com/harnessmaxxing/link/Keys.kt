package com.harnessmaxxing.link

/** What a `key` input becomes on Android. */
sealed class KeyAction {
    /** `AccessibilityService.performGlobalAction(action)`. */
    data class Global(val action: Int) : KeyAction()
    /** The IME action of the focused field (send, search, next line...): ACTION_IME_ENTER. */
    data object Enter : KeyAction()
    /** Delete the selection or the character before the cursor of the focused field. */
    data object Backspace : KeyAction()
    data class Unsupported(val name: String) : KeyAction()
}

object Keys {
    // Values of AccessibilityService.GLOBAL_ACTION_* (stable since API 16-28).
    const val GLOBAL_BACK = 1
    const val GLOBAL_HOME = 2
    const val GLOBAL_RECENTS = 3
    const val GLOBAL_NOTIFICATIONS = 4
    const val GLOBAL_QUICK_SETTINGS = 5
    const val GLOBAL_POWER_DIALOG = 6
    const val GLOBAL_LOCK_SCREEN = 8

    /** Names accepted by `key`, for error messages. */
    const val SUPPORTED = "back, home, recents, notifications, quick_settings, enter, backspace, power, lock"

    fun map(raw: String): KeyAction = when (raw.trim().lowercase().replace(' ', '_').replace('-', '_')) {
        "back", "escape", "esc" -> KeyAction.Global(GLOBAL_BACK)
        "home" -> KeyAction.Global(GLOBAL_HOME)
        "recents", "recent_apps", "overview", "app_switch" -> KeyAction.Global(GLOBAL_RECENTS)
        "notifications", "notification_shade" -> KeyAction.Global(GLOBAL_NOTIFICATIONS)
        "quick_settings" -> KeyAction.Global(GLOBAL_QUICK_SETTINGS)
        "power", "power_dialog" -> KeyAction.Global(GLOBAL_POWER_DIALOG)
        "lock", "lock_screen" -> KeyAction.Global(GLOBAL_LOCK_SCREEN)
        "enter", "return", "ime_enter", "send", "search", "go", "done" -> KeyAction.Enter
        "backspace", "delete", "del" -> KeyAction.Backspace
        else -> KeyAction.Unsupported(raw)
    }
}
