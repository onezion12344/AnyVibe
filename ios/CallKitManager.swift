import Foundation
import CallKit
import Combine

// MARK: - CallKitManager
/// Owns the CXProvider and CXCallController.
/// Handles all CallKit delegate actions and orchestrates the call lifecycle:
///   reportNewIncomingCall → answer → activate audio → end call
final class CallKitManager: NSObject, ObservableObject {

    // MARK: Published
    @Published var activeCallUUID: UUID?
    @Published var isMuted = false
    @Published var isOnHold = false

    // MARK: Dependencies
    private let audioSession: AudioSessionManager
    private let audioEngine: AudioEngineManager
    private let webSocket: WebSocketConnection

    // MARK: CX Objects
    let provider: CXProvider
    private let callController = CXCallController()

    // MARK: Init
    init(audioSession: AudioSessionManager, audioEngine: AudioEngineManager, webSocket: WebSocketConnection) {
        self.audioSession = audioSession
        self.audioEngine = audioEngine
        self.webSocket = webSocket

        let config = CXProviderConfiguration(localizedName: "Coding Vibe Voice")
        config.supportsVideo = false
        config.maximumCallsPerCallGroup = 1
        config.supportedHandleTypes = [.phoneNumber]
        config.iconTemplateImageData = nil
        config.ringtoneSound = "ringtone.caf"
        config.includesCallsInRecents = true

        self.provider = CXProvider(configuration: config)
        super.init()
        provider.setDelegate(self, queue: nil)
    }
}

// MARK: - Public API
extension CallKitManager {

    /// Place an outgoing call — call this from the UI when the user dials a number.
    func startOutgoingCall(handle: String) {
        let uuid = UUID()
        let cxHandle = CXHandle(type: .phoneNumber, value: handle)
        let startAction = CXStartCallAction(call: uuid, handle: cxHandle)
        startAction.isVideo = false

        let transaction = CXTransaction(action: startAction)
        callController.request(transaction) { [weak self] error in
            if let error = error {
                print("[CallKitManager] Start call request failed: \(error.localizedDescription)")
            }
        }
        activeCallUUID = uuid
    }

    /// Answer the currently ringing incoming call.
    func answerCall(uuid: UUID) {
        let action = CXAnswerCallAction(call: uuid)
        let transaction = CXTransaction(action: action)
        callController.request(transaction) { error in
            if let error = error {
                print("[CallKitManager] Answer call failed: \(error.localizedDescription)")
            }
        }
    }

    /// End the active call.
    func endCall(uuid: UUID) {
        let action = CXEndCallAction(call: uuid)
        let transaction = CXTransaction(action: action)
        callController.request(transaction) { error in
            if let error = error {
                print("[CallKitManager] End call failed: \(error.localizedDescription)")
            }
        }
        activeCallUUID = nil
    }

    /// Toggle microphone mute.
    func setMuted(_ muted: Bool) {
        guard let uuid = activeCallUUID else { return }
        let action = CXSetMutedCallAction(call: uuid, muted: muted)
        let transaction = CXTransaction(action: action)
        callController.request(transaction) { error in
            if let error = error {
                print("[CallKitManager] Mute toggle failed: \(error.localizedDescription)")
            }
        }
        isMuted = muted
    }
}

// MARK: - CXProviderDelegate
extension CallKitManager: CXProviderDelegate {

    // MARK: Outgoing call — system asks us to start
    func provider(_ provider: CXProvider, perform action: CXStartCallAction) {
        print("[CallKitManager] Performing CXStartCallAction — UUID: \(action.callUUID)")

        // Configure (but do NOT activate) the audio session here
        audioSession.configure()
        action.fulfill()
    }

    // MARK: Incoming call — user taps Answer
    func provider(_ provider: CXProvider, perform action: CXAnswerCallAction) {
        print("[CallKitManager] Performing CXAnswerCallAction — UUID: \(action.callUUID)")

        audioSession.configure()
        action.fulfill()
    }

    // MARK: User taps Decline / Hang up
    func provider(_ provider: CXProvider, perform action: CXEndCallAction) {
        print("[CallKitManager] Performing CXEndCallAction — UUID: \(action.callUUID)")

        audioEngine.stop()
        webSocket.disconnect()
        audioSession.deactivate()
        action.fulfill()
        activeCallUUID = nil
    }

    // MARK: Hold / Unhold
    func provider(_ provider: CXProvider, perform action: CXSetHeldCallAction) {
        isOnHold = action.isOnHold
        if action.isOnHold {
            audioSession.deactivate()
        } else {
            audioSession.activate()
        }
        action.fulfill()
    }

    // MARK: Mute / Unmute
    func provider(_ provider: CXProvider, perform action: CXSetMutedCallAction) {
        isMuted = action.isMuted
        action.fulfill()
    }

    // MARK: ⚠️ CRITICAL — Audio Session Activated
    /// The system calls this **only after** it has elevated your audio session priority.
    /// Start the WebSocket and audio engine HERE — not earlier.
    func provider(_ provider: CXProvider, didActivate audioSession: AVAudioSession) {
        print("[CallKitManager] Audio session activated — starting WebSocket + audio engine")
        webSocket.connect(callUUID: activeCallUUID ?? UUID())
        try? audioEngine.start()
    }

    // MARK: Audio Session Deactivated
    func provider(_ provider: CXProvider, didDeactivate audioSession: AVAudioSession) {
        print("[CallKitManager] Audio session deactivated — stopping audio engine")
        audioEngine.stop()
    }

    // MARK: Timed Out
    func provider(_ provider: CXProvider, timedOutPerforming action: CXAction) {
        print("[CallKitManager] Action timed out: \(type(of: action))")
        action.fulfill()
    }

    // MARK: Reset (incoming call cancelled before answer)
    func provider(_ provider: CXProvider, didReset incomingCall: UUID) {
        print("[CallKitManager] Incoming call reset — UUID: \(incomingCall)")
        audioEngine.stop()
        webSocket.disconnect()
    }
}
