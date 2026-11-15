package com.harnessmaxxing.link

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.textfield.TextInputEditText

class MainActivity : AppCompatActivity() {

    private lateinit var config: Config
    private val refresh: () -> Unit = { render() }
    @Volatile private var pairing = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.root)) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        config = Config(this)

        findViewById<Button>(R.id.accessibility_button).setOnClickListener {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        findViewById<Button>(R.id.app_info_button).setOnClickListener {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
        }
        findViewById<Button>(R.id.notifications_button).setOnClickListener {
            if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        findViewById<Button>(R.id.pair_button).setOnClickListener {
            pair(text(R.id.server_input), text(R.id.code_input))
        }
        findViewById<Button>(R.id.pause_button).setOnClickListener {
            LinkService.start(this, if (config.paused) LinkService.ACTION_RESUME else LinkService.ACTION_PAUSE)
            // The service flips the flag; show it at once.
            config.paused = !config.paused
            render()
        }
        findViewById<Button>(R.id.forget_button).setOnClickListener {
            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.forget_title)
                .setMessage(R.string.forget_text)
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.forget_confirm) { _, _ ->
                    config.forget()
                    stopService(Intent(this, LinkService::class.java))
                    LinkState.set(LinkState.Conn.NOT_PAIRED, null)
                    render()
                }
                .show()
        }
        val name = findViewById<TextInputEditText>(R.id.name_input)
        name.setText(config.name)
        name.setOnEditorActionListener { _, action, _ ->
            if (action == EditorInfo.IME_ACTION_DONE) { saveName(); false } else false
        }
        name.setOnFocusChangeListener { _, has -> if (!has) saveName() }

        handleLink(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleLink(intent)
    }

    override fun onStart() {
        super.onStart()
        LinkState.observe(refresh)
        if (config.paired) LinkService.start(this)
        render()
    }

    override fun onStop() {
        LinkState.unobserve(refresh)
        super.onStop()
    }

    private fun text(id: Int) = findViewById<TextInputEditText>(id).text?.toString().orEmpty()

    private fun saveName() {
        val v = text(R.id.name_input).trim()
        if (v.isEmpty() || v == config.name) return
        config.name = v
        Toast.makeText(this, R.string.name_saved, Toast.LENGTH_SHORT).show()
        if (config.paired) LinkService.start(this, LinkService.ACTION_RECONNECT)
    }

    /** `harnesslink://pair?s=...&c=...`: always confirmed by the person (a link can come from anyone). */
    private fun handleLink(intent: Intent?) {
        val data = intent?.data ?: return
        intent.data = null
        val link = PairLink.parse(data.toString()) ?: return
        findViewById<TextInputEditText>(R.id.server_input).setText(link.server)
        findViewById<TextInputEditText>(R.id.code_input).setText(link.code)
        val host = PairLink.host(link.server)
        var msg = getString(R.string.pair_confirm_text)
        if (config.paired) msg += "\n\n" + getString(R.string.pair_confirm_replace)
        MaterialAlertDialogBuilder(this)
            .setTitle(getString(R.string.pair_confirm_title, host))
            .setMessage(msg)
            .setNegativeButton(R.string.cancel, null)
            .setPositiveButton(R.string.pair_button) { _, _ -> pair(link.server, link.code) }
            .show()
    }

    private fun pair(server: String, code: String) {
        if (pairing) return
        pairing = true
        val button = findViewById<Button>(R.id.pair_button)
        button.isEnabled = false
        button.setText(R.string.pairing)
        Thread {
            if (config.paired) {
                stopService(Intent(this, LinkService::class.java))
                config.forget()
            }
            val r = Pairing.pair(applicationContext, server, code)
            runOnUiThread {
                pairing = false
                button.isEnabled = true
                button.setText(R.string.pair_button)
                val message = when (r) {
                    Pairing.Result.Ok -> {
                        LinkService.start(this)
                        getString(R.string.pair_ok)
                    }
                    is Pairing.Result.Failed -> when (r.reason) {
                        Pairing.Reason.BAD_SERVER -> getString(R.string.pair_bad_server)
                        Pairing.Reason.BAD_CODE -> getString(R.string.pair_bad_code)
                        Pairing.Reason.EXPIRED -> getString(R.string.pair_expired)
                        Pairing.Reason.NETWORK -> getString(R.string.pair_network, r.detail)
                        Pairing.Reason.SERVER -> getString(R.string.pair_server, r.detail)
                    }
                }
                Toast.makeText(this, message, Toast.LENGTH_LONG).show()
                render()
            }
        }.start()
    }

    private fun render() {
        val paired = config.paired
        val a11y = LinkAccessibilityService.enabled
        val title = findViewById<TextView>(R.id.status_title)
        val detail = findViewById<TextView>(R.id.status_detail)
        when {
            !paired -> {
                title.setText(R.string.status_not_paired)
                detail.setText(if (LinkState.lastError == "revoked") R.string.status_revoked_detail else R.string.status_not_paired_detail)
            }
            config.paused -> {
                title.setText(R.string.status_paused); detail.setText(R.string.status_paused_detail)
            }
            !a11y -> {
                title.setText(R.string.status_accessibility_off); detail.setText(R.string.status_accessibility_off_detail)
            }
            LinkState.conn == LinkState.Conn.CONNECTED -> {
                title.setText(when (LinkState.busyBy) {
                    "claude" -> R.string.status_claude
                    "human" -> R.string.status_human
                    else -> R.string.status_connected
                })
                detail.setText(R.string.status_connected_detail)
            }
            else -> {
                title.setText(R.string.status_connecting)
                detail.text = LinkState.lastError?.let { getString(R.string.status_offline_detail, it) } ?: ""
            }
        }
        findViewById<View>(R.id.accessibility_block).visibility = if (a11y) View.GONE else View.VISIBLE
        val needNotif = Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        findViewById<View>(R.id.notifications_button).visibility = if (needNotif) View.VISIBLE else View.GONE
        findViewById<View>(R.id.pair_block).visibility = if (paired) View.GONE else View.VISIBLE
        findViewById<View>(R.id.paired_block).visibility = if (paired) View.VISIBLE else View.GONE
        if (paired) {
            findViewById<TextView>(R.id.server_label).text = getString(R.string.server_label, config.server)
            findViewById<Button>(R.id.pause_button).setText(if (config.paused) R.string.resume else R.string.pause)
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        render()
    }
}
