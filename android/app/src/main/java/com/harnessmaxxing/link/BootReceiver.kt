package com.harnessmaxxing.link

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Reopens the link after a restart of the phone or an update of the app, once paired. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (Config(context).paired) LinkService.start(context)
    }
}
