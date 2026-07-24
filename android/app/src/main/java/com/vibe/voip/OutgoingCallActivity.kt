package com.vibe.voip

import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

/**
 * Dial-pad UI for placing an outgoing self-managed VoIP call.
 *
 * Tapping "Call" invokes TelecomManager.placeCall(), which flows through
 * MyConnectionService.onCreateOutgoingConnection() → VoIPConnection.
 *
 * Alternatively, you can use this screen purely for self-managed audio
 * without ConnectionService plumbing — uncomment the direct audio path below.
 */
class OutgoingCallActivity : AppCompatActivity() {

    private lateinit var numberInput: EditText
    private lateinit var callButton: Button
    private lateinit var statusText: TextView

    companion object {
        const val EXTRA_SERVER_URL = "server_url"
        const val EXTRA_CALL_TOKEN = "call_token"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_outgoing_call)

        numberInput = findViewById(R.id.numberInput)
        callButton  = findViewById(R.id.callButton)
        statusText  = findViewById(R.id.statusText)

        callButton.setOnClickListener { placeCall() }
    }

    private fun placeCall() {
        val number = numberInput.text.toString().trim()
        if (number.isEmpty()) {
            Toast.makeText(this, "Enter a number or SIP address", Toast.LENGTH_SHORT).show()
            return
        }

        val handle = android.net.Uri.fromParts("tel", number, null)

        val extras = Bundle().apply {
            putString("server_url", intent.getStringExtra(EXTRA_SERVER_URL) ?: "")
            putString("call_token", intent.getStringExtra(EXTRA_CALL_TOKEN) ?: "")
        }

        try {
            val telecomManager = getSystemService(TELECOM_SERVICE) as android.telecom.TelecomManager
            telecomManager.placeCall(handle, extras)
            statusText.text = "Calling $number …"
            callButton.isEnabled = false
        } catch (e: SecurityException) {
            Toast.makeText(this, "MANAGE_OWN_CALLS permission missing", Toast.LENGTH_LONG).show()
        }
    }

    // ── Alternative: self-managed call without ConnectionService ──────────────
    // Uncomment this method and remove the placeCall() dependency on
    // ConnectionService if you prefer to manage the AudioEngine directly.
    /*
    private fun callDirectly() {
        val serverUrl = intent.getStringExtra(EXTRA_SERVER_URL) ?: return
        val callToken = intent.getStringExtra(EXTRA_CALL_TOKEN) ?: return

        val engine = WebSocketAudioEngine(serverUrl, callToken)
        Executors.newSingleThreadExecutor().execute(engine)

        statusText.text = "Call active (self-managed)"
        Toast.makeText(this, "Audio connected directly", Toast.LENGTH_SHORT).show()

        // TODO: call engine.stop() in onDestroy()
    }
    */
}
