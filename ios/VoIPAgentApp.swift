import SwiftUI

/// Root SwiftUI view.
/// Replace the placeholder with your real UI once you have the CallScreen wired.
@main
struct VoIPAgentApp: App {

    // Attach AppDelegate so didFinishLaunchingWithOptions runs
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}

// MARK: - ContentView
/// Minimal placeholder — swap in your call UI.
struct ContentView: View {
    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                Image(systemName: "phone.badge.waveform")
                    .font(.system(size: 64))
                    .foregroundStyle(.blue)
                Text("VoIP Agent")
                    .font(.largeTitle).bold()
                Text("Ready to place and receive calls")
                    .foregroundStyle(.secondary)
                Spacer()
            }
            .padding()
            .navigationTitle("VoIP Agent")
            .toolbar {
                NavigationLink("Dialer") {
                    DialerView()
                }
            }
        }
    }
}

// MARK: - DialerView
/// Simple number pad for placing outgoing calls.
struct DialerView: View {
    @State private var dialedNumber = ""

    private let keys = [
        ["1","2","3"],
        ["4","5","6"],
        ["7","8","9"],
        ["*","0","#"]
    ]

    var body: some View {
        VStack(spacing: 12) {
            // Number display
            Text(dialedNumber.isEmpty ? "Enter number" : dialedNumber)
                .font(.system(size: 32, weight: .medium, design: .monospaced))
                .foregroundStyle(dialedNumber.isEmpty ? .secondary : .primary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 24)

            // Keypad
            ForEach(keys, id: \.self) { row in
                HStack(spacing: 12) {
                    ForEach(row, id: \.self) { key in
                        Button(action: { dialedNumber += key }) {
                            Text(key)
                                .font(.system(size: 28, weight: .semibold))
                                .frame(maxWidth: .infinity)
                                .frame(height: 64)
                                .background(.ultraThinMaterial)
                                .clipShape(Circle())
                        }
                    }
                }
            }

            // Call button
            Button(action: {
                // TODO: wire to CallKitManager.startOutgoingCall(handle: dialedNumber)
                print("Place call to: \(dialedNumber)")
            }) {
                Label("Call", systemImage: "phone.fill")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(.green)
                    .foregroundStyle(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 16))
            }
            .disabled(dialedNumber.isEmpty)
            .padding(.top, 12)

            // Backspace
            Button(action: {
                guard !dialedNumber.isEmpty else { return }
                dialedNumber.removeLast()
            }) {
                Image(systemName: "delete.left")
                    .font(.title2)
                    .padding()
            }
        }
        .padding()
        .navigationTitle("Dialer")
    }
}

// MARK: - CallScreen
/// Active-call UI: mute, end, speaker toggle.
struct CallScreen: View {
    let callerName: String
    let callHandle: String

    @Environment(\.dismiss) private var dismiss
    @State private var isMuted = false
    @State private var isSpeakerOn = false

    var body: some View {
        VStack(spacing: 32) {
            Spacer()

            // Caller avatar + name
            VStack(spacing: 12) {
                Circle()
                    .fill(.blue.gradient)
                    .frame(width: 100, height: 100)
                    .overlay {
                        Image(systemName: "person.fill")
                            .font(.system(size: 48))
                            .foregroundStyle(.white)
                    }
                Text(callerName)
                    .font(.title).bold()
                Text(callHandle)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Text("Calling…")
                    .font(.caption)
                    .foregroundStyle(.green)
            }

            Spacer()

            // Control buttons
            HStack(spacing: 40) {
                // Mute
                CallButton(
                    systemImage: isMuted ? "mic.slash.fill" : "mic.fill",
                    label: "Mute",
                    isActive: isMuted,
                    color: isMuted ? .red : .blue
                ) {
                    // TODO: wire to CallKitManager.setMuted(!isMuted)
                    isMuted.toggle()
                }

                // End call
                CallButton(
                    systemImage: "phone.down.fill",
                    label: "End",
                    isActive: true,
                    color: .red,
                    isLarge: true
                ) {
                    // TODO: wire to CallKitManager.endCall(uuid:)
                    dismiss()
                }

                // Speaker
                CallButton(
                    systemImage: isSpeakerOn ? "speaker.wave.2.fill" : "speaker.fill",
                    label: "Speaker",
                    isActive: isSpeakerOn,
                    color: isSpeakerOn ? .blue : .gray
                ) {
                    isSpeakerOn.toggle()
                    // TODO: route audio to speaker via AVAudioSession overrideOutputAudioPort
                }
            }
            .padding(.bottom, 48)
        }
        .background(.ultraThinMaterial)
    }
}

// MARK: - CallButton
struct CallButton: View {
    let systemImage: String
    let label: String
    let isActive: Bool
    let color: Color
    let isLarge: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 6) {
                Image(systemName: systemImage)
                    .font(.system(size: isLarge ? 28 : 20))
                    .foregroundStyle(.white)
                    .frame(width: isLarge ? 72 : 56, height: isLarge ? 72 : 56)
                    .background(color)
                    .clipShape(Circle())
                Text(label)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
