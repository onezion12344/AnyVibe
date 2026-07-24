import Foundation
import AVFoundation

// MARK: - AudioEngineManager
/// Captures microphone audio via AVAudioSinkNode and plays incoming audio via
/// AVAudioPlayerNode.  The caller is responsible for Opus encoding before sending
/// and Opus decoding before calling playRemoteAudio.
final class AudioEngineManager: NSObject {

    // MARK: Properties
    private let engine = AVAudioEngine()
    private let playerNode = AVAudioPlayerNode()
    private let audioSession = AudioSessionManager()

    private var isRunning = false
    private let sampleRate: Double = 48_000   // Opus native rate

    // MARK: Callback — called on the engine's render thread with raw PCM float data.
    /// Wrap this in an Opus encoder before sending over WebSocket.
    var onAudioBuffer: ((AVAudioPCMBuffer) -> Void)?

    // MARK: Start
    func start() throws {
        guard !isRunning else { return }

        audioSession.configure()
        audioSession.activate()

        // Install a SinkNode to tap the microphone stream
        let sinkNode = AVAudioSinkNode { [weak self] buffer, when in
            guard let self = self else { return }
            self.onAudioBuffer?(buffer)
            // Returning nil from the tap means "don't silence audio routing"
            return []
        }

        engine.attach(sinkNode)
        let inputNode = engine.inputNode
        let inputFormat = inputNode.outputFormat(forBus: 0)

        // Connect mic → sink node
        engine.connect(inputNode, to: sinkNode, format: inputFormat)

        // Connect player node to output (speaker / AirPods)
        let outputFormat = engine.outputNode.outputFormat(forBus: 0)
        engine.attach(playerNode)
        engine.connect(playerNode, to: engine.mainMixerNode, format: outputFormat)

        try engine.start()
        playerNode.play()
        isRunning = true
        print("[AudioEngineManager] Audio engine started")
    }

    // MARK: Stop
    func stop() {
        guard isRunning else { return }
        playerNode.stop()
        engine.stop()
        engine.reset()
        isRunning = false
        print("[AudioEngineManager] Audio engine stopped")
    }

    // MARK: Play Remote Audio
    /// Call this from your WebSocket receive callback with decoded PCM Float32 data.
    /// The caller decodes the Opus frame before passing the PCM buffer here.
    func playRemoteAudio(pcmBuffer: AVAudioPCMBuffer) {
        guard isRunning else { return }
        playerNode.scheduleBuffer(pcmBuffer, completionHandler: nil)
    }
}
