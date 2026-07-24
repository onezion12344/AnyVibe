# iOS VoIP App — Setup Guide

A CallKit + PushKit + WebSocket VoIP app. Handles incoming calls via APNs VoIP push and outgoing calls via `CXCallController`. Audio streams over WebSocket to `wss://<host>/api/call`.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Xcode 15+ | iOS 17+ SDK target |
| Physical iOS device | PushKit & CallKit do **not** work in the Simulator |
| Apple Developer account | For App ID, APNs VoIP push key, and signing |
| Backend server | Sends VoIP pushes and relays WebSocket audio frames |

---

## Step 1 — Xcode Project Setup

1. Open Xcode → **New Project** → **iOS → App** (SwiftUI, Swift)
2. Name the project (e.g. `VoIPAgentApp`). Delete the default files and drop the sources in this folder in.
3. Add the files in this `ios/` folder to the Xcode project (drag-and-drop into the project navigator, tick "Copy items if needed").

### Capabilities (Signing & Capabilities tab)

| Capability | How to add |
|---|---|
| **Push Notifications** | Click `+ Capability` → **Push Notifications** |
| **Background Modes** | Click `+ Capability` → **Background Modes** → tick: **Voice over IP**, **Audio, AirPlay, and Picture in Picture** |

### Entitlements (`<AppName>.entitlements`)

Xcode auto-generates this when you add Push Notifications. Verify it contains:

```xml
<key>aps-environment</key>
<string>development</string>   <!-- or "production" for App Store -->
```

---

## Step 2 — Info.plist

Add these keys to `Info.plist`:

```xml
<key>UIBackgroundModes</key>
<array>
    <string>voip</string>
    <string>audio</string>
</array>
<key>NSMicrophoneUsageDescription</key>
<string>This app uses the microphone to transmit your voice during calls.</string>
<key>NSLocationWhenInUseUsageDescription</key>
<string>This app uses location to improve call quality in poor network conditions.</string>
```

---

## Step 3 — Apple Developer Portal

1. **Create an App ID** (`com.yourcompany.voipagent`) with **Push Notifications** and **Background Modes** enabled.
2. **Create an APNs Auth Key** (`.p8`):
   - Developer Portal → Certificates, IDs & Profiles → Keys → `+`
   - Name it (e.g. `VoIPAPNsKey`) → enable **Apple Push Notification service (APNs)**
   - Download the `.p8` file — **you cannot download it again**.
   - Note the **Key ID** and your **Team ID**.
3. In your App ID page under **Push Notifications**, click **Configure** and upload the `.p8` key (or use a VoIP-specific certificate — both work; the key covers both regular and VoIP pushes).

---

## Step 4 — APNs VoIP Push Topic

Your VoIP push topic is **always** `<bundleID>.voip` — the `.voip` suffix is mandatory. If you send a push with just `<bundleID>`, APNs returns `TopicDisallowed (400)`.

```
# Example
Bundle ID:      com.yourcompany.voipagent
VoIP topic:     com.yourcompany.voipagent.voip   ← .voip suffix required
```

---

## Step 5 — Server-Side: Register Device Token & Send VoIP Push

Your server must:

1. **Receive the VoIP device token** from the app (sent in `PushRegistryManager.pushRegistry(_:didUpdate:for:)`) — this is a different token from the regular APNs token.
2. **Send VoIP pushes** with the correct headers:

```bash
curl --http2 \
  --cert ./voip_cert.pem \
  https://api.sandbox.push.apple.com:443/3/device/<voip-device-token> \
  -d '{"aps":{"content-available":1},"handle":"1234567890","callerName":"Alice","uuid":"<call-uuid>"}' \
  -H "apns-topic: com.yourcompany.voipagent.voip" \
  -H "apns-push-type: voip" \
  -H "apns-priority: 10" \
  -H "apns-expiration: 0"
```

Or use the `apn` npm package (recommended):

```js
const apn = require('apn');
const provider = new apn.Provider({
  token: { key: 'APNKey.p8', keyId: 'YOUR_KEY_ID', teamId: 'YOUR_TEAM_ID' },
  production: false   // true for TestFlight / App Store
});

const note = new apn.Notification();
note.pushType = 'voip';
note.topic = 'com.yourcompany.voipagent.voip';
note.payload = { aps: { 'content-available': 1 }, handle: '+15551234567', callerName: 'Alice' };

provider.send(note, voipDeviceToken);
```

---

## Step 6 — WebSocket Server

The app connects to `wss://<host>/api/call`. Expected protocol:

| Direction | Message |
|---|---|
| App → Server | Binary: Opus-encoded 20 ms audio frame (48 kHz mono) |
| App → Server | Text JSON: `{"type": "join", "callUUID": "<uuid>"}` on connect |
| Server → App | Binary: Opus-encoded audio frame from the remote party |

The audio codec is **Opus** — use `opus-swift` or `libopus` via Swift Package Manager to encode/decode. Native 48 kHz mono PCM → Opus frames at 20 ms resolution.

---

## Step 7 — PushKit & CallKit Setup in Code

The key wiring (all in `PushRegistryManager` + `CallKitManager`):

```
Server VoIP push (APNs)
    → didReceiveIncomingPushWith
    → provider.reportNewIncomingCall   ← MUST call for EVERY push (iOS 13+ rule)
    → user taps Answer
    → provider(_:perform: CXAnswerCallAction)
    → provider(_:didActivate:)          ← START WebSocket + audio engine here
    ← provider(_:didDeactivate:)        ← STOP everything here
```

### Outgoing Call

```
callManager.startCall(handle: "+15551234567")
    → CXProviderDelegate.provider(_:perform: CXStartCallAction)
    → provider.reportOutgoingCall(...)
    → provider(_:didActivate:)          ← START WebSocket + audio engine
```

---

## Critical Gotchas

| Gotcha | Fix |
|---|---|
| **CallKit required with PushKit (iOS 13+)** | You cannot use PushKit without CallKit. Always call `reportNewIncomingCall`. |
| **Call `reportNewIncomingCall` for EVERY push** | Even cancellation/rejection pushes. Apple DTS confirmed this in 2026. Use `reportCall(with:updated:)` to update later. |
| **VoIP device token ≠ regular APNs token** | `PKPushRegistry` gives you a VoIP-specific token. Send it to your server separately. |
| **`.voip` topic suffix is mandatory** | Without it APNs returns `TopicDisallowed (400)`. |
| **Always call `action.fulfill()` or `action.fail()`** | Omitting either leaves the CXAction pending forever. |
| **Start audio only in `didActivate`** | Never start the audio engine in `perform CXAnswerCallAction` — the system elevates audio session priority only in `didActivate`. |
| **~30 s background window after VoIP push** | Do the minimum: report the call to CallKit and connect the WebSocket. Use `beginBackgroundTask` if you need more time. |
| **Does not work in Simulator** | Use a physical device for all PushKit / CallKit testing. |
| **All devices receive the push** | If the user has the app on iPhone + iPad, both get the VoIP push. The answering device signals the other(s) to end via your signaling server, not via another push. |

---

## File Structure

```
ios/
├── Models/
│   ├── CallModel.swift          # Call data model
│   └── WebSocketConnection.swift# WebSocket client for audio streaming
├── PushRegistryManager.swift    # PKPushRegistry + VoIP push handling
├── CallKitManager.swift         # CXProvider + CXCallController
├── AudioSessionManager.swift    # AVAudioSession configure / activate / deactivate
├── AudioEngineManager.swift     # AVAudioEngine + AVAudioSinkNode (mic tap + playback)
├── AppDelegate.swift            # App entry point, PushKit registration
├── Views/
│   └── CallScreen.swift         # Active-call UI
├── Info.plist                   # Background modes + mic permission
└── <AppName>.entitlements       # aps-environment entitlement
```
