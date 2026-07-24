# Vibe VoIP — Android Scaffold

A Gradle-ready Kotlin Android app that demonstrates a self-managed VoIP call pipeline:
incoming calls triggered by high-priority FCM data messages, outgoing calls via
the Telecom framework, and bidirectional PCM audio streamed over a WebSocket.

## File Map

```
android/
├── build.gradle.kts                  # Root Gradle config (repositories, includes :app)
├── settings.gradle.kts               # Plugin management, rootProject name
├── gradle.properties                 # JVM args, AndroidX flags
└── app/
    ├── build.gradle.kts              # App-level dependencies: Firebase BOM, OkHttp
    └── src/main/
        ├── AndroidManifest.xml       # Permissions + all 4 service/activity declarations
        ├── java/com/vibe/voip/
        │   ├── AppInitializer.kt          # Application class — registers PhoneAccount
        │   ├── MyFirebaseMessagingService.kt  # FCM receiver → starts CallForegroundService
        │   ├── CallForegroundService.kt   # Foreground service; calls addNewIncomingCall()
        │   ├── MyConnectionService.kt     # ConnectionService — system binds here
        │   ├── VoIPConnection.kt          # Connection — manages call state + audio engine
        │   ├── WebSocketAudioEngine.kt    # AudioRecord/AudioTrack + OkHttp WebSocket
        │   └── OutgoingCallActivity.kt    # Dial-pad Activity for placing outgoing calls
        ├── res/
        │   ├── layout/activity_outgoing_call.xml
        │   ├── values/strings.xml
        │   ├── values/themes.xml
        │   ├── mipmap-{mdpi,hdpix,xhdpi,xxhdpi,xxxhdpi}/  ← auto-generated icons
        │   └── xml/                      # backup/data-extraction rules
        └── google-services.json          ← PLACEHOLDER — see Setup below
```

## Architecture (call flow)

```
FCM high-priority data message
  → MyFirebaseMessagingService.onMessageReceived()
    → CallForegroundService (started as foreground)
      → TelecomManager.addNewIncomingCall(handle, extras)
        → System binds to MyConnectionService
          → onCreateIncomingConnection() returns VoIPConnection
            → onAnswer() → WebSocketAudioEngine.start()
              → AudioRecord → WebSocket → wss://host/api/call
              ← WebSocket ← AudioTrack → speaker
```

## Setup Steps

### 1. Firebase project

1. Open https://console.firebase.google.com → create project → add Android app.
2. Package name: `com.vibe.voip`.
3. Download `google-services.json` and place it at  
   `android/app/google-services.json` (replace the placeholder).

### 2. FCM server key

In Firebase Console → Project Settings → Cloud Messaging, copy the **Server key**
(legacy HTTP API key). Use it as a Bearer token in the WebSocket connection or in
your push-sender code.

Example FCM HTTP v1 request (data-only, high-priority):

```json
POST https://fcm.googleapis.com/v1/projects/<project-id>/messages:send
Authorization: Bearer <OAuth2-token>

{
  "message": {
    "token": "<device-fcm-token>",
    "android": { "priority": "high" },
    "data": {
      "type": "incoming_call",
      "caller_id": "+85212345678",
      "caller_name": "Alice",
      "server_url": "wss://your-server.com/api/call",
      "call_token": "<jwt-or-session-token>"
    }
  }
}
```

> **Do NOT include a `"notification"` key** — that makes it a notification
> message, which the system handles itself and `onMessageReceived()` never fires.

### 3. MANAGE_OWN_CALLS permission

`MANAGE_OWN_CALLS` is declared in the manifest as a **normal** permission — no
runtime prompt is needed. However, the app crashes with `SecurityException` if
the permission is not present, so verify with:

```bash
adb shell dumpsys package com.vibe.voip | grep MANAGE_OWN_CALLS
```

### 4. Android 14 full-screen intent

On Android 14+ `USE_FULL_SCREEN_INTENT` must be auto-granted (call/alarm core
functionality) or user-granted. Check at runtime:

```kotlin
val nm = getSystemService(NotificationManager::class.java)
val canFSI = nm.canUseFullScreenIntent()   // Android 14+
```

Do NOT use `ContextCompat.checkSelfPermission(USE_FULL_SCREEN_INTENT)` — that
returns `GRANTED` unconditionally on API 34 due to a platform bug.

### 5. Runtime permissions (request at first launch)

```kotlin
// Android 13+ — POST_NOTIFICATIONS is a runtime permission
ActivityCompat.requestPermissions(
    this,
    arrayOf(Manifest.permission.POST_NOTIFICATIONS, Manifest.permission.RECORD_AUDIO),
    REQUEST_CODE
)
```

### 6. Build

```bash
cd android
./gradlew assembleDebug
```

Or open the `android/` directory in Android Studio.

## WebSocket Audio Protocol

The default protocol is **raw 16-bit PCM** — each WebSocket message is exactly
640 bytes (20 ms at 16 kHz mono). For production, prepend each frame with:

| Offset | Size | Field |
|--------|------|-------|
| 0      | 4 B  | Sequence number (uint32 LE) |
| 4      | 4 B  | Timestamp in ms (uint32 LE) |
| 8      | 640 B| Raw PCM frame |

Server-side expectations:
- Accept WebSocket connections at `wss://<host>/api/call`.
- Authorize via `Authorization: Bearer <call_token>` header or `?token=` query.
- Forward received PCM frames to the other party's WebSocket.

## Key Gotchas

| Issue | Fix |
|---|---|
| `addNewIncomingCall()` from a background context | Always call from a running foreground service; FCM `onMessageReceived()` is an allowed background-start path when `priority=high` |
| 5-second FGS rule | Call `startForeground()` within 5 s of `startForegroundService()` — do NOT do heavy work first |
| FCM doze wake | Use `priority: "high"` in the FCM message body |
| Audio quality | Use `AudioSource.VOICE_COMMUNICATION`, not `MIC` — echo cancellation and AGC are built in |
| App killed while call active | `CAPABILITY_SELF_MANAGED` keeps the system VoIP audio path alive; the foreground service keeps the process alive |
| OEM battery-kill | Ask the user to whitelist the app from battery optimisation (especially Xiaomi, Oppo, Vivo) |
| Frame size for latency | 20 ms frames (640 bytes) give ~30–50 ms end-to-end latency; larger frames = less CPU but more latency |
