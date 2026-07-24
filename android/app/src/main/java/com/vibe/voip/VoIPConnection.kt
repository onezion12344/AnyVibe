package com.vibe.voip

import android.os.Build
import android.telecom.Connection
import android.telecom.DisconnectCause
import android.util.Log
import java.util.concurrent.Executors

/**
 * A single VoIP call connection.
 * Manages the full call lifecycle: initialise → dialing → active → disconnect,
 * and owns the WebSocket audio engine.
 *
 * The connection runs its audio engine on a single background thread to avoid
 * crossing thread boundaries for AudioRecord/AudioTrack calls (these are NOT
 * thread-safe).
 */
class VoIPConnection : Connection() {

    companion object {
        private const val TAG = "VoIPConnection"
        private const val EXTRA_SERVER_URL = "server_url"
        private const val EXTRA_CALL_TOKEN = "call_token"
    }

    private var audioEngine: WebSocketAudioEngine? = null
    private val executor = Executors.newSingleThreadExecutor()

    init {
        // Mark as self-managed so the system does not route audio through the
        // cellular modem.
        setConnectionProperties(PROPERTY_SELF_MANAGED)
        // Tell Android this is VoIP — routes audio to the correct audio device
        // and enables built-in echo cancellation.
        setAudioModeIsVoip(true)
        // The app supplies its own UI (CallActivity / notification chrome).
        setCallerDisplayName("")
    }

    // ── System callbacks ────────────────────────────────────────────────────

    override fun onAnswer() {
        super.onAnswer()
        Log.d(TAG, "onAnswer")
        setActive()
        startAudio()
    }

    override fun onReject() {
        super.onReject()
        Log.d(TAG, "onReject")
        stopAudio()
        setDisconnected(DisconnectCause(DisconnectCause.REJECTED))
        destroy()
    }

    override fun onAbort() {
        super.onAbort()
        Log.d(TAG, "onAbort")
        stopAudio()
        setDisconnected(DisconnectCause(DisconnectCause.CANCELED))
        destroy()
    }

    override fun onDisconnect() {
        super.onDisconnect()
        Log.d(TAG, "onDisconnect")
        stopAudio()
        setDisconnected(DisconnectCause(DisconnectCause.LOCAL))
        destroy()
    }

    override fun onHold() {
        super.onHold()
        audioEngine?.muteMic()
        setOnHold()
    }

    override fun onUnhold() {
        super.onUnhold()
        audioEngine?.unmuteMic()
        setActive()
    }

    // ── Audio ───────────────────────────────────────────────────────────────

    private fun startAudio() {
        val serverUrl = extras?.getString(EXTRA_SERVER_URL).orEmpty()
        val callToken = extras?.getString(EXTRA_CALL_TOKEN).orEmpty()

        if (serverUrl.isBlank() || callToken.isBlank()) {
            Log.e(TAG, "Missing server_url or call_token — aborting call")
            onAbort()
            return
        }

        audioEngine = WebSocketAudioEngine(serverUrl, callToken).also { engine ->
            executor.execute(engine)
        }
    }

    private fun stopAudio() {
        audioEngine?.stop()
        audioEngine = null
    }

    override fun onDestroy() {
        super.onDestroy()
        stopAudio()
        executor.shutdownNow()
    }
}
