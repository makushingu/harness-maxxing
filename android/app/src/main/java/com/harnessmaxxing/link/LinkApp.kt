package com.harnessmaxxing.link

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager

class LinkApp : Application() {
    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        val ch = NotificationChannel(CHANNEL, getString(R.string.channel_name), NotificationManager.IMPORTANCE_LOW)
        ch.description = getString(R.string.channel_description)
        ch.setShowBadge(false)
        nm.createNotificationChannel(ch)
    }

    companion object {
        const val CHANNEL = "link"
    }
}
