package com.vibe.voip

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat

/**
 * Foreground service that hosts an active VoIP call.
 * The system requires addNewIncomingCall() to be invoked from a running
 * foreground service on Android 10+.
 *
 * This service is started (not bound) and manages its own lifecycle:
 *  - ACTION_HANDLE_INCOMING_CALL: triggers TelecomManager.addNewIncomingCall()
 *    then promotes itself to foreground with an in-call notification.
 *  - ACTION_END_CALL: stops audio and stops the service.
 */
class CallForegroundService : Service() {

    companion object {
        private const val TAG = "CallForegroundService"

        const val ACTION_HANDLE_INCOMING_CALL = "action.HANDLE_INCOMING_CALL"
        const val ACTION_END_CALL = "action.END_CALL"
        const val ACTION_ANSWER = "action.ANSWER"
        const val ACTION_DECLINE = "action.DECLINE"

        const val NOTIFICATION_ID = 1001
        const val CHANNEL_ID = "vibe_voip_call"

        const val EXTRA_CALLER_ID = "caller_id"
        const val EXTRA_CALLER_NAME = "caller_name"
        const val EXTRA_SERVER_URL = "server_url"
        const val EXTRA_CALL_TOKEN = "call_token"

        private const val REQ_ANSWER = 2001
        private const val REQ_DECLINE = 2002
    }

    private lateinit var telecomManager: android.telecom.TelecomManager
    private lateinit var notificationManager: NotificationManager

    override fun onCreate() {
        super.onCreate()
        telecomManager = getSystemService(TELECOM_SERVICE) as android.telecom.TelecomManager
        notificationManager = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_HANDLE_INCOMING_CALL -> handleIncomingCall(intent)
            ACTION_END_CALL -> endCall()
            ACTION_ANSWER -> answerCall()
            ACTION_DECLINE -> declineCall()
        }
        // Keep running until we explicitly stop; system can restart us if killed.
        return START_STICKY
    }

    private fun handleIncomingCall(intent: Intent) {
        val callerName = intent.getStringExtra(EXTRA_CALLER_NAME) ?: "Unknown"
        val callerId = intent.getStringExtra(EXTRA_CALLER_ID) ?: ""
        val serverUrl = intent.getStringExtra(EXTRA_SERVER_URL) ?: ""
        val callToken = intent.getStringExtra(EXTRA_CALL_TOKEN) ?: ""

        Log.d(TAG, "handleIncomingCall: $callerName ($callerId)")

        // Build the incoming-call extras for TelecomManager
        val extras = Bundle().apply {
            putString("android.telecom.extra.INCOMING_CALL_ADDRESS", "tel:$callerId")
            putString(EXTRA_CALLER_NAME, callerName)
            putString(EXTRA_SERVER_URL, serverUrl)
            putString(EXTRA_CALL_TOKEN, callToken)
        }

        try {
            // Triggers the system to bind to MyConnectionService and create a Connection.
            telecomManager.addNewIncomingCall(
                com.vibe.voip.AppInitializer.getPhoneAccountHandle(this),
                extras
            )
        } catch (e: SecurityException) {
            Log.e(TAG, "Missing MANAGE_OWN_CALLS permission", e)
            return
        }

        // Promote to foreground with the ringing call notification
        // (must be called within 5 s of startForegroundService()).
        startForeground(NOTIFICATION_ID, buildIncomingCallNotification(callerName))
    }

    private fun buildIncomingCallNotification(callerName: String): Notification {
        val answerIntent = PendingIntent.getService(
            this, REQ_ANSWER,
            Intent(this, CallForegroundService::class.java).setAction(ACTION_ANSWER),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val declineIntent = PendingIntent.getService(
            this, REQ_DECLINE,
            Intent(this, CallForegroundService::class.java).setAction(ACTION_DECLINE),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            Notification.Builder(this, CHANNEL_ID)
                .setCategory(Notification.CATEGORY_CALL)
                .setPriority(Notification.PRIORITY_HIGH)
                .setOngoing(true)
                .setAutoCancel(false)
                .setStyle(
                    Notification.CallStyle.forIncomingCall(
                        Notification.Person.Builder()
                            .setName(callerName)
                            .setImportant(true)
                            .build(),
                        answerIntent,
                        declineIntent
                    )
                )
                .build()
        } else {
            // Fallback for API 23-30 (no CallStyle)
            NotificationCompat.Builder(this, CHANNEL_ID)
                .setCategory(Notification.CATEGORY_CALL)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setOngoing(true)
                .setAutoCancel(false)
                .setContentTitle("Incoming call")
                .setContentText(callerName)
                .addAction(0, "Answer", answerIntent)
                .addAction(0, "Decline", declineIntent)
                .build()
        }
    }

    private fun answerCall() {
        // The ConnectionService lifecycle callback (onAnswer) takes care of audio.
        // We just dismiss the ringing notification here.
        notificationManager.cancel(NOTIFICATION_ID)
        // TODO: replace with active-call notification if you want persistent UI
    }

    private fun declineCall() {
        stopSelf()
    }

    private fun endCall() {
        stopSelf()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Call Notifications",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Incoming and active call notifications"
                setSound(null, null) // CallStyle handles the ringtone
            }
            notificationManager.createNotificationChannel(channel)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        super.onDestroy()
        Log.d(TAG, "Service destroyed")
    }
}
