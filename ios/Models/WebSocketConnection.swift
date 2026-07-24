import Foundation

// MARK: - WebSocketConnection
/// Manages the WebSocket connection to wss://<host>/api/call
/// Sends and receives raw audio frames (the caller handles Opus encoding/decoding).
class WebSocketConnection: ObservableObject {

    // MARK: Published State
    @Published var isConnected = false
    @Published var connectionState: ConnectionState = .disconnected

    enum ConnectionState: String {
        case disconnected
        case connecting
        case connected
        case failed
    }

    // MARK: Properties
    private var webSocketTask: URLSessionWebSocketTask?
    private let session = URLSession(configuration: .default)
    private let host: String
    private var pingTimer: Timer?

    // MARK: Callbacks
    var onIncomingAudioFrame: ((Data) -> Void)?
    var onStateChange: ((ConnectionState) -> Void)?

    // MARK: Init
    init(host: String = "localhost") {
        self.host = host
    }

    // MARK: Connect
    func connect(callUUID: UUID) {
        guard connectionState != .connected && connectionState != .connecting else {
            return
        }

        updateState(.connecting)

        let url = URL(string: "wss://\(host)/api/call")!
        webSocketTask = session.webSocketTask(with: url)
        webSocketTask?.resume()

        // Send a "join" frame so the server associates this socket with the call
        let joinPayload: [String: Any] = [
            "type": "join",
            "callUUID": callUUID.uuidString
        ]
        sendJSON(joinPayload)

        // Start ping/pong keep-alive
        startPing()

        // Listen for incoming messages
        listen()
    }

    // MARK: Disconnect
    func disconnect() {
        stopPing()
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        updateState(.disconnected)
    }

    // MARK: Send Audio Frame
    /// Call this from the audio engine sink callback.
    /// Pass raw PCM bytes — the caller is responsible for Opus encoding before this.
    func sendAudioFrame(_ data: Data) {
        webSocketTask?.send(.data(data)) { [weak self] error in
            if let error = error {
                print("WebSocket audio send error: \(error.localizedDescription)")
                self?.updateState(.failed)
            }
        }
    }

    // MARK: Send JSON Control Message
    func sendJSON(_ dict: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: dict) else { return }
        webSocketTask?.send(.data(data)) { [weak self] error in
            if let error = error {
                print("WebSocket JSON send error: \(error.localizedDescription)")
            }
        }
    }

    // MARK: Private — Listen Loop
    private func listen() {
        webSocketTask?.receive { [weak self] result in
            guard let self = self else { return }

            switch result {
            case .failure(let error):
                print("WebSocket receive error: \(error.localizedDescription)")
                self.updateState(.failed)
            case .success(let message):
                switch message {
                case .data(let data):
                    self.handleIncomingMessage(data)
                case .string(let text):
                    // Control messages (JSON strings)
                    if let data = text.data(using: .utf8),
                       let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                       let type = json["type"] as? String {
                        self.handleControlMessage(type: type, payload: json)
                    }
                @unknown default:
                    break
                }
            }

            // Continue listening
            self.listen()
        }
    }

    // MARK: Private — Handle Incoming Audio
    private func handleIncomingMessage(_ data: Data) {
        // Assume binary = audio frame (Opus-encoded). Caller decodes and plays.
        onIncomingAudioFrame?(data)
    }

    // MARK: Private — Handle Control Messages
    private func handleControlMessage(type: String, payload: [String: Any]) {
        switch type {
        case "joined":
            updateState(.connected)
        case "error":
            if let msg = payload["message"] as? String {
                print("WebSocket server error: \(msg)")
            }
            updateState(.failed)
        default:
            break
        }
    }

    // MARK: Private — Ping Keep-Alive
    private func startPing() {
        pingTimer = Timer.scheduledTimer(withTimeInterval: 20.0, repeats: true) { [weak self] _ in
            self?.webSocketTask?.sendPing { error in
                if let error = error {
                    print("WebSocket ping failed: \(error.localizedDescription)")
                }
            }
        }
    }

    private func stopPing() {
        pingTimer?.invalidate()
        pingTimer = nil
    }

    // MARK: Private — State Update
    private func updateState(_ newState: ConnectionState) {
        DispatchQueue.main.async {
            self.connectionState = newState
            self.isConnected = (newState == .connected)
            self.onStateChange?(newState)
        }
    }
}
