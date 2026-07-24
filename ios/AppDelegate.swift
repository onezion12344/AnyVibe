import Foundation
import UIKit
import SwiftUI

// MARK: - AppDelegate
/// Application entry point. Registers PushKit for VoIP pushes and wires together
/// CallKitManager, PushRegistryManager, AudioSessionManager, AudioEngineManager,
/// and WebSocketConnection.
///
/// In a pure-SwiftUI project (no SceneDelegate), also add this to
/// `<AppName>.swift` (the @main struct):
///   @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
@main
class AppDelegate: UIResponder, UIApplicationDelegate {

    // MARK: Shared singletons (one set per process)
    private var callKitManager: CallKitManager!
    private var pushRegistryManager: PushRegistryManager!
    private var audioSessionManager: AudioSessionManager!
    private var audioEngineManager: AudioEngineManager!
    private var webSocketConnection: WebSocketConnection!

    // MARK: Launch
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
    ) -> Bool {

        // ── Wire up the dependency graph ──────────────────────────────────────
        audioSessionManager = AudioSessionManager()
        audioEngineManager = AudioEngineManager()
        webSocketConnection = WebSocketConnection(host: "localhost") // TODO: set your server host
        callKitManager = CallKitManager(
            audioSession: audioSessionManager,
            audioEngine: audioEngineManager,
            webSocket: webSocketConnection
        )
        pushRegistryManager = PushRegistryManager(
            callKitManager: callKitManager,
            webSocket: webSocketConnection
        )

        // Wire audio engine output → WebSocket (encode → send)
        // NOTE: The caller should replace the raw Data pass-through below with
        // actual Opus encoding. See AudioEngineManager.onAudioBuffer docs.
        audioEngineManager.onAudioBuffer = { [weak self] buffer in
            self?.handleAudioBuffer(buffer)
        }

        // Wire WebSocket incoming audio → audio engine player node
        webSocketConnection.onIncomingAudioFrame = { [weak self] data in
            self?.handleIncomingAudioFrame(data)
        }

        // ── Register for VoIP pushes ───────────────────────────────────────────
        pushRegistryManager.registerForVoIPPushes()

        // ── Also register for regular APNs pushes (optional, for non-call notifications) ──
        application.registerForRemoteNotifications()

        return true
    }

    // MARK: Audio Buffer → WebSocket
    /// Called from the AVAudioSinkNode tap.
    /// Replace the direct Data cast with Opus encoding before sending.
    private func handleAudioBuffer(_ buffer: AVAudioPCMBuffer) {
        // TODO: Encode with Opus first (e.g. opus-swift or libopus SPM package)
        // For now we pass raw PCM float data — the server must handle this format
        // or you swap in an OpusEncoder here.
        let frameLength = Int(buffer.frameLength)
        let channelData = buffer.floatChannelData?[0]
        let pcmData = Data(bytes: channelData!, count: frameLength * MemoryLayout<Float>.size)
        webSocketConnection.sendAudioFrame(pcmData)
    }

    // MARK: WebSocket → Audio Engine
    /// Called when the WebSocket receives a binary audio frame from the server.
    /// Replace the pass-through with Opus decode → AVAudioPCMBuffer → playerNode.
    private func handleIncomingAudioFrame(_ data: Data) {
        // TODO: Decode Opus frame → AVAudioPCMBuffer, then call audioEngine.playRemoteAudio
        // For now just log so you can verify the data path works before adding codec bindings.
        print("[AppDelegate] Incoming audio frame: \(data.count) bytes")
    }

    // MARK: UISceneSession (iOS 13+)
    func application(
        _ application: UIApplication,
        configurationForConnecting connectingSceneSession: UISceneSession,
        options: UIScene.ConnectionOptions
    ) -> UISceneConfiguration {
        UISceneConfiguration(name: "Default Configuration", sessionRole: connectingSceneSession.role)
    }
}
