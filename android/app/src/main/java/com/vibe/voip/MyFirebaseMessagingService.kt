package com.vibe.voip

import android.util.Log
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

/**
 * Receives FCM data messages.
 * Only data messages (no "notification" key) arrive here even when the app is
 * backgrounded or killed, making them ideal for triggering incoming VoIP calls.
 *
 * Send FCM payload example (HTTP v1 or legacy):
 *   { "priority": "high",
 *     "data": {
 *       "type": "incoming_call",
 *       "caller_id": "+85212345678",
 *       "caller_name": "Alice",
 *       "server_url": "wss://your-server.com/call",
 *       "call_token": "<jwt_or_session_token>"
 *     }
 *   }
 */
class MyFirebaseMessagingService : FirebaseMessagingService() {

    companion object {
        private const val TAG = "MyFirebaseMsgService"
    }

    override fun onMessageReceived(remoteMessage: RemoteMessage) {
        Log.d(TAG, "FCM message received from: ${remoteMessage.from}")

        val payload = remoteMessage.data
        if (payload["type"] != "incoming_call") return

        Log.i(TAG, "Incoming call FCM: ${payload["caller_name"]} <${payload["caller_id"]}>")

        // FCM's onMessageReceived() is an allowed background-start path on
        // Android 10+ (per the platform background-start allowlist).
        val intent = Intent(this, CallForegroundService::class.java).apply {
            action = CallForegroundService.ACTION_HANDLE_INCOMING_CALL
            putExtras(Bundle().apply {
                putString(CallForegroundService.EXTRA_CALLER_ID, payload["caller_id"])
                putString(CallForegroundService.EXTRA_CALLER_NAME, payload["caller_name"])
                putString(CallForegroundService.EXTRA_SERVER_URL, payload["server_url"])
                putString(CallForegroundService.EXTRA_CALL_TOKEN, payload["call_token"])
            })
        }

        androidx.core.content.ContextCompat.startForegroundService(this, intent)
    }

    override fun onNewToken(token: String) {
        Log.i(TAG, "New FCM token: $token")
        // TODO: send token to your backend so it can address this device
    }
}
