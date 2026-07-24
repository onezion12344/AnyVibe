import Foundation
import PushKit
import CallKit
import Combine

// MARK: - PushRegistryManager
/// Wraps PKPushRegistry for VoIP push registration and incoming-push handling.
/// On every VoIP push it extracts call metadata and reports it to CallKit via
/// `provider.reportNewIncomingCall(with:update:)` — required on every push by iOS 13+.
@MainActor
final class PushRegistryManager: NSObject {

    // MARK: Dependencies
    private let voipRegistry: PKPushRegistry
    private let provider: CXProvider
    private let callKitManager: CallKitManager
    private let webSocket: WebSocketConnection

    // MARK: Published
    @Published var voipToken: String?

    // MARK: Combine bag
    private var cancellables = Set<AnyCancellable>()

    // MARK: Init
    init(callKitManager: CallKitManager, webSocket: WebSocketConnection) {
        self.callKitManager = callKitManager
        self.webSocket = webSocket
        self.voipRegistry = PKPushRegistry(queue: .main)
        self.provider = callKitManager.provider
        super.init()
        voipRegistry.delegate = self
    }

    // MARK: Registration
    func registerForVoIPPushes() {
        voipRegistry.desiredPushTypes = [.voIP]
    }
}

// MARK: - PKPushRegistryDelegate
extension PushRegistryManager: PKPushRegistryDelegate {

    /// APNs issued a new device token — send it to your backend so the server
    /// can target this device with VoIP pushes.
    func pushRegistry(
        _ registry: PKPushRegistry,
        didUpdate pushCredentials: PKPushCredentials,
        for type: PKPushType
    ) {
        guard type == .voIP else { return }
        let token = pushCredentials.token
            .map { String(format: "%02.2hhx", $0) }
            .joined()
        voipToken = token
        print("[PushRegistryManager] VoIP device token: \(token)")
        // TODO: POST token to your backend server
    }

    /// Called when the system delivers a VoIP push while the app is in the
    /// background (or suspended). You get ~30 s of background execution time.
    func pushRegistry(
        _ registry: PKPushRegistry,
        didReceiveIncomingPushWith payload: PKPushPayload,
        for type: PKPushType,
        completion: @escaping () -> Void
    ) {
        guard type == .voIP else {
            completion()
            return
        }

        handleVoIPPush(payload: payload.dictionaryPayload, completion: completion)
    }

    // MARK: Private — Push Handler
    private func handleVoIPPush(payload: [AnyHashable: Any], completion: @escaping () -> Void) {
        print("[PushRegistryManager] Received VoIP push: \(payload)")

        // Extract call metadata from the push payload
        let handle  = payload["handle"]  as? String ?? "unknown"
        let caller  = payload["callerName"] as? String ?? "Unknown Caller"
        let uuidStr = payload["uuid"]     as? String ?? UUID().uuidString
        let callUUID = UUID(uuidString: uuidStr) ?? UUID()

        // Build the CallKit update
        let callUpdate = CXCallUpdate()
        callUpdate.remoteHandle = CXHandle(type: .phoneNumber, value: handle)
        callUpdate.localizedCallerName = caller
        callUpdate.hasVideo = false
        callUpdate.supportsDTMF = true
        callUpdate.supportsHolding = true
        callUpdate.supportsGrouping = false
        callUpdate.supportsUngrouping = false

        // ⚠️ iOS 13+ HARD RULE: MUST call reportNewIncomingCall for EVERY VoIP push,
        // even if you plan to immediately end the call or it is a duplicate.
        provider.reportNewIncomingCall(with: callUUID, update: callUpdate) { [weak self] error in
            if let error = error {
                print("[PushRegistryManager] reportNewIncomingCall failed: \(error.localizedDescription)")
            } else {
                print("[PushRegistryManager] Incoming call reported to CallKit — UUID: \(callUUID)")
            }

            // Kick off WebSocket connection in parallel (starts media negotiation)
            self?.webSocket.connect(callUUID: callUUID)

            // Tell the system we are done processing the push
            completion()
        }
    }
}
