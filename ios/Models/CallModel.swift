import Foundation
import CallKit

// MARK: - CallDirection
enum CallDirection: String, Codable {
    case incoming
    case outgoing
}

// MARK: - CallState
enum CallState: String, Codable {
    case connecting
    case ringing
    case connected
    case ended
    case failed
}

// MARK: - CallModel
struct CallModel: Identifiable, Codable {
    let id: UUID
    let handle: String
    let callerName: String
    let direction: CallDirection
    var state: CallState
    var isMuted: Bool
    var isOnHold: Bool

    init(
        id: UUID = UUID(),
        handle: String,
        callerName: String,
        direction: CallDirection,
        state: CallState = .connecting,
        isMuted: Bool = false,
        isOnHold: Bool = false
    ) {
        self.id = id
        self.handle = handle
        self.callerName = callerName
        self.direction = direction
        self.state = state
        self.isMuted = isMuted
        self.isOnHold = isOnHold
    }
}
