// Traduko macOS speech helper: JSON-lines CLI over SpeechAnalyzer.
//
// Subcommands:
//   probe                          capabilities + locale lists
//   assets --locale <bcp47>        download model assets with progress
//   transcribe --file <path> [--locale <bcp47>]   segments as JSON lines
//
// Every output line is one JSON object. Errors: {"error": "..."} and a
// nonzero exit. Requires macOS 26+ at runtime (weak availability checks);
// on older systems probe reports os_ok=false instead of crashing.

import AVFoundation
import Foundation
import Speech

func emit(_ payload: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: payload),
          let line = String(data: data, encoding: .utf8) else { return }
    print(line)
    fflush(stdout)
}

func fail(_ message: String) -> Never {
    emit(["error": message])
    exit(1)
}

func argument(_ name: String) -> String? {
    let arguments = CommandLine.arguments
    guard let index = arguments.firstIndex(of: name), index + 1 < arguments.count else {
        return nil
    }
    return arguments[index + 1]
}

@available(macOS 26, *)
func bcp47(_ locale: Locale) -> String {
    return locale.identifier(.bcp47)
}

@available(macOS 26, *)
func resolveLocale(hint: String, supported: [Locale]) -> Locale? {
    if hint.isEmpty {
        let current = Locale.current
        if supported.contains(where: { bcp47($0) == bcp47(current) }) {
            return current
        }
        return supported.first
    }
    if let exact = supported.first(where: { bcp47($0).lowercased() == hint.lowercased() }) {
        return exact
    }
    let language = hint.split(separator: "-").first.map(String.init)?.lowercased() ?? hint.lowercased()
    return supported.first { bcp47($0).lowercased().hasPrefix(language) }
}

@available(macOS 26, *)
func runProbe() async {
    let transcriberLocales = await SpeechTranscriber.supportedLocales
    let dictationLocales = await DictationTranscriber.supportedLocales
    let installed = await SpeechTranscriber.installedLocales
    emit([
        "available": !transcriberLocales.isEmpty,
        "os_ok": true,
        "transcriber_locales": transcriberLocales.map(bcp47),
        "dictation_locales": dictationLocales.map(bcp47),
        "installed": installed.map(bcp47),
    ])
}

@available(macOS 26, *)
func runAssets(localeHint: String) async {
    let supported = await SpeechTranscriber.supportedLocales
    guard let locale = resolveLocale(hint: localeHint, supported: supported) else {
        fail("locale not supported: \(localeHint)")
    }
    let transcriber = SpeechTranscriber(
        locale: locale,
        transcriptionOptions: [],
        reportingOptions: [],
        attributeOptions: [.audioTimeRange]
    )
    do {
        if let request = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
            let progress = request.progress
            let watcher = Task {
                while !Task.isCancelled {
                    emit(["progress": progress.fractionCompleted])
                    try? await Task.sleep(for: .seconds(1))
                }
            }
            try await request.downloadAndInstall()
            watcher.cancel()
        }
        emit(["progress": 1.0])
        emit(["done": true, "locale": bcp47(locale)])
    } catch {
        fail("asset install failed: \(error)")
    }
}

@available(macOS 26, *)
func runTranscribe(path: String, localeHint: String) async {
    let url = URL(fileURLWithPath: path)
    guard FileManager.default.fileExists(atPath: path) else {
        fail("file not found: \(path)")
    }
    let supported = await SpeechTranscriber.supportedLocales
    if let locale = resolveLocale(hint: localeHint, supported: supported) {
        await transcribeSpeech(url: url, locale: locale)
        return
    }
    // Language outside SpeechTranscriber's list: fall back to the wider
    // DictationTranscriber locale set.
    let dictationSupported = await DictationTranscriber.supportedLocales
    guard let locale = resolveLocale(hint: localeHint, supported: dictationSupported) else {
        fail("locale not supported: \(localeHint)")
    }
    await transcribeDictation(url: url, locale: locale)
}

@available(macOS 26, *)
func transcribeSpeech(url: URL, locale: Locale) async {
    do {
        let transcriber = SpeechTranscriber(
            locale: locale,
            transcriptionOptions: [],
            reportingOptions: [],
            attributeOptions: [.audioTimeRange]
        )
        if let request = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
            try await request.downloadAndInstall()
        }
        let analyzer = SpeechAnalyzer(modules: [transcriber])
        let file = try AVAudioFile(forReading: url)
        let collector = Task {
            var lastEnd = 0.0
            for try await result in transcriber.results {
                guard result.isFinal else { continue }
                let text = String(result.text.characters)
                let range = result.range
                let start = range.isValid ? range.start.seconds : lastEnd
                let end = range.isValid ? range.end.seconds : lastEnd
                lastEnd = end
                emit(["start": start, "end": end, "text": text])
            }
            return lastEnd
        }
        if let lastSample = try await analyzer.analyzeSequence(from: file) {
            try await analyzer.finalizeAndFinish(through: lastSample)
        } else {
            try await analyzer.cancelAndFinishNow()
        }
        let duration = try await collector.value
        emit(["done": true, "duration": duration, "locale": bcp47(locale)])
    } catch {
        fail("transcription failed: \(error)")
    }
}

@available(macOS 26, *)
func transcribeDictation(url: URL, locale: Locale) async {
    do {
        let transcriber = DictationTranscriber(
            locale: locale,
            contentHints: [],
            transcriptionOptions: [],
            reportingOptions: [],
            attributeOptions: [.audioTimeRange]
        )
        if let request = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
            try await request.downloadAndInstall()
        }
        let analyzer = SpeechAnalyzer(modules: [transcriber])
        let file = try AVAudioFile(forReading: url)
        let collector = Task {
            var lastEnd = 0.0
            for try await result in transcriber.results {
                guard result.isFinal else { continue }
                let text = String(result.text.characters)
                let range = result.range
                let start = range.isValid ? range.start.seconds : lastEnd
                let end = range.isValid ? range.end.seconds : lastEnd
                lastEnd = end
                emit(["start": start, "end": end, "text": text])
            }
            return lastEnd
        }
        if let lastSample = try await analyzer.analyzeSequence(from: file) {
            try await analyzer.finalizeAndFinish(through: lastSample)
        } else {
            try await analyzer.cancelAndFinishNow()
        }
        let duration = try await collector.value
        emit(["done": true, "duration": duration, "locale": bcp47(locale)])
    } catch {
        fail("transcription failed: \(error)")
    }
}

// Entry point: swiftc single-file script mode allows top-level await
// (SE-0343), which sidesteps @main's top-level-code restriction.
let arguments = CommandLine.arguments
guard arguments.count >= 2 else {
    fail("usage: helper <probe|assets|transcribe> [options]")
}
if #available(macOS 26, *) {
    switch arguments[1] {
    case "probe":
        await runProbe()
    case "assets":
        await runAssets(localeHint: argument("--locale") ?? "")
    case "transcribe":
        guard let file = argument("--file") else { fail("--file is required") }
        await runTranscribe(path: file, localeHint: argument("--locale") ?? "")
    default:
        fail("unknown subcommand: \(arguments[1])")
    }
} else {
    emit(["available": false, "os_ok": false, "error": "requires macOS 26 or newer"])
    exit(0)
}
