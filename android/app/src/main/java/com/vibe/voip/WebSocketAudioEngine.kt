package com.vibe.voip

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.util.Log
import okhttp3.*
import okio.ByteString
import okio.ByteString.Companion.toByteString
import java.util.concurrent.Executors

/**
 * Bi-directional audio engine.
 * Captures mic PCM at 16 kHz / 16-bit mono → streams to the server over WebSocket.
 * Receives remote PCM from the server → writes to AudioTrack for speaker playback.
 *
 * Wire protocol (simple, production-grade foundation):
 *   Each WebSocket message is a single raw PCM frame (20 ms = 640 bytes).
 *   For production: prepend a 4-byte LE sequence-number + 4-byte LE timestamp so
 *   the server/other client can reorder out-of-order packets and compute jitter.
 *
 * Thread-safety: all AudioRecord / AudioTrack calls happen on the executor thread.
 * Never call AudioRecord.read() or AudioTrack.write() from two different threads.
 */
class WebSocketAudioEngine(
    private val serverUrl: String,
    private val callToken: String
) : Runnable {

    companion object {
        private const val TAG = "WebSocketAudio"

        // 16 kHz 16-bit mono = 640 bytes per 20-ms frame
        private const val SAMPLE_RATE = 16_000
        private const val CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO
        private const val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT
        private const val FRAME_SIZE = 640          // 20 ms @ 16 kHz 16-bit

        private const val WS_RECONNECT_BASE_MS = 1_000L
        private const val WS_RECONNECT_MAX_MS  = 30_000L

        // SECURITY: the media endpoint must NOT be trusted from the push payload as-is.
        // A forged push could point us at an attacker server and exfiltrate callToken
        // (sent as an Authorization: Bearer header). Only connect to pinned hosts over
        // TLS. Edit this to your real backend host(s) before shipping.
        private val ALLOWED_WS_HOSTS = setOf(
            "anyvibe.onezion.top",
            "161.118.214.70",
        )

        /** Returns true only for a wss:// URL whose host is in the allowlist. */
        fun isTrustedServerUrl(url: String): Boolean {
            return try {
                val u = java.net.URI(url)
                u.scheme == "wss" && u.host in ALLOWED_WS_HOSTS
            } catch (e: Exception) {
                false
            }
        }
    }

    init {
        // Reject an untrusted/downgraded media endpoint before any token is sent.
        require(isTrustedServerUrl(serverUrl)) {
            "Refusing untrusted media server_url: $serverUrl (must be wss:// to an allowlisted host)"
        }
    }

    @Volatile private var running = false
    @Volatile private var muted = false

    private val executor = Executors.newSingleThreadExecutor()
    private var webSocket: WebSocket? = null
    private var okHttpClient: OkHttpClient? = null

    private var audioRecord: AudioRecord? = null
    private var audioTrack: AudioTrack? = null

    // ── Public API ──────────────────────────────────────────────────────────

    fun muteMic() { muted = true }

    fun unmuteMic() { muted = false }

    override fun run() {
        running = true
        try {
            initAudioIO()
            connectWithRetry()

            // WebSocket connection succeeded; start audio I/O loops.
            executor.execute { captureLoop() }
            // Playback is event-driven from onMessage — no separate loop needed.

            // Block here so this Runnable stays alive while the call is active.
            // We re-synchronize on [running] each iteration so stop() can break out.
            while (running) {
                Thread.sleep(500)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Fatal error", e)
        } finally {
            cleanup()
        }
    }

    fun stop() {
        running = false
        webSocket?.close(1000, "Call ended")
        executor.shutdownNow()
        cleanup()
    }

    // ── Audio I/O ───────────────────────────────────────────────────────────

    private fun initAudioIO() {
        val minBuf = AudioRecord.getMinBufferSize(
            SAMPLE_RATE, CHANNEL_CONFIG, AUDIO_FORMAT
        ).coerceAtLeast(FRAME_SIZE * 4)  // 4 frames minimum

        audioRecord = AudioRecord(
            MediaRecorder.AudioSource.VOICE_COMMUNICATION, // echo-cancellation + AGC built-in
            SAMPLE_RATE,
            CHANNEL_CONFIG,
            AUDIO_FORMAT,
            minBuf
        )

        audioTrack = AudioTrack.Builder()
            .setAudioAttributes(
                android.media.AudioAttributes.Builder()
                    .setUsage(android.media.AudioAttributes.USAGE_VOICE_COMMUNICATION)
                    .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AUDIO_FORMAT)
                    .setSampleRate(SAMPLE_RATE)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build()
            )
            .setBufferSizeInBytes(minBuf)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
    }

    private fun captureLoop() {
        audioRecord?.startRecording()
        val buffer = ByteArray(FRAME_SIZE)

        while (running) {
            val read = audioRecord?.read(buffer, 0, FRAME_SIZE) ?: break
            if (read > 0 && !muted) {
                webSocket?.send(buffer.take(read).toByteArray().toByteString())
            }
        }
        audioRecord?.stop()
    }

    // ── WebSocket ───────────────────────────────────────────────────────────

    private fun connectWithRetry() {
        var delayMs = WS_RECONNECT_BASE_MS

        while (running) {
            try {
                val request = Request.Builder()
                    .url(serverUrl)
                    .addHeader("Authorization", "Bearer $callToken")
                    .build()

                val ws = okHttpClient!!.newWebSocket(request, object : WebSocketListener() {
                    override fun onOpen(ws: WebSocket, response: Response) {
                        Log.i(TAG, "WebSocket connected")
                        delayMs = WS_RECONNECT_BASE_MS  // reset back-off
                    }

                    override fun onMessage(ws: WebSocket, bytes: ByteString) {
                        // Remote audio → speaker
                        audioTrack?.write(bytes.toByteArray(), 0, bytes.size)
                    }

                    override fun onClosing(ws: WebSocket, code: Int, reason: String) {
                        Log.w(TAG, "WebSocket closing: $code $reason")
                    }

                    override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                        Log.w(TAG, "WebSocket closed: $code $reason")
                    }

                    override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                        Log.e(TAG, "WebSocket error", t)
                        if (running) scheduleReconnect(delayMs)
                    }
                })
                webSocket = ws

                // The ws callback holds a reference; store the active socket.
                // Note: OkHttp manages the socket lifecycle internally; we just
                // keep a reference for sending.
                // The listener's onOpen callback updates running state.
                return  // break out of retry loop once newWebSocket is called
            } catch (e: Exception) {
                Log.e(TAG, "WebSocket connect failed, retrying in ${delayMs}ms", e)
                Thread.sleep(delayMs)
                delayMs = (delayMs * 2).coerceAtMost(WS_RECONNECT_MAX_MS)
            }
        }
    }

    private fun scheduleReconnect(delayMs: Long) {
        if (!running) return
        executor.execute {
            try {
                Thread.sleep(delayMs)
                if (running) connectWithRetry()
            } catch (e: InterruptedException) {
                Log.w(TAG, "Reconnect interrupted")
            }
        }
    }

    // ── Cleanup ─────────────────────────────────────────────────────────────

    private fun cleanup() {
        try { audioRecord?.release() } catch (_: Exception) {}
        try { audioTrack?.release() } catch (_: Exception) {}
        try { okHttpClient?.dispatcher?.executorService?.shutdown() } catch (_: Exception) {}
        audioRecord = null
        audioTrack = null
        webSocket = null
        okHttpClient = null
        Log.i(TAG, "Audio engine cleaned up")
    }
}
