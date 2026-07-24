import Foundation
import AVFoundation

// MARK: - AudioSessionManager
/// Encapsulates AVAudioSession configuration.
/// Configure here — activate / deactivate is driven by CallKit (didActivate / didDeactivate).
final class AudioSessionManager {

    private let audioSession = AVAudioSession.sharedInstance()

    /// Set category and mode. Do NOT call setActive(true) here — CallKit handles activation.
    func configure() {
        do {
            try audioSession.setCategory(.playAndRecord, mode: .voiceChat, options: [
                .allowBluetooth,
                .defaultToSpeaker,
                .interruptSpokenAudioAndMixWithOthers,
                .allowBluetoothA2DP   // optional: AirPods stereo
            ])
            // Mode .voiceChat activates built-in AEC + AGC + noise suppression
            print("[AudioSessionManager] Audio session configured: playAndRecord / voiceChat")
        } catch {
            print("[AudioSessionManager] setCategory failed: \(error.localizedDescription)")
        }
    }

    /// Activate — called by CallKit via didActivate, or manually if needed.
    func activate() {
        do {
            try audioSession.setActive(true)
            print("[AudioSessionManager] Audio session activated")
        } catch {
            print("[AudioSessionManager] setActive(true) failed: \(error.localizedDescription)")
        }
    }

    /// Deactivate — called by CallKit via didDeactivate, or on call end.
    func deactivate() {
        do {
            try audioSession.setActive(false)
            print("[AudioSessionManager] Audio session deactivated")
        } catch {
            print("[AudioSessionManager] setActive(false) failed: \(error.localizedDescription)")
        }
    }
}
