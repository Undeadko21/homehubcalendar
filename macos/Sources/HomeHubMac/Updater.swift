import Foundation
import AppKit

/// Автообновление: сервер дома раздаёт свежую сборку (`/api/app-mac`), приложение сравнивает номер сборки
/// со своим, скачивает zip, заменяет себя и перезапускается. Нужен доступ к серверу дома (вне дома — вручную).
@MainActor
final class Updater: ObservableObject {
    static let shared = Updater()

    struct Info: Equatable {
        let build: Int
        let version: String
        let url: URL
    }

    enum State: Equatable {
        case idle, checking, upToDate, available(Info), installing, failed(String)
    }

    @Published private(set) var state: State = .idle
    @Published var auto: Bool { didSet { UserDefaults.standard.set(auto, forKey: "autoUpdate") } }

    private init() {
        auto = UserDefaults.standard.object(forKey: "autoUpdate") as? Bool ?? true
    }

    static var currentBuild: Int { Int(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "") ?? 0 }
    static var currentVersion: String { Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?" }
    /// Запуск не из .app (например, swift run) — обновлять нечего.
    static var canUpdate: Bool { Bundle.main.bundleIdentifier != nil && Bundle.main.bundleURL.pathExtension == "app" }

    /// Проверка при запуске и раз в 6 часов.
    func loop(_ model: AppModel) async {
        guard Self.canUpdate else { return }
        try? await Task.sleep(nanoseconds: 20_000_000_000)
        while !Task.isCancelled {
            await check(model.serverBase, quiet: true)
            try? await Task.sleep(nanoseconds: 6 * 3600 * 1_000_000_000)
        }
    }

    func check(_ base: URL?, quiet: Bool = false) async {
        guard Self.canUpdate else { state = .failed("обновление работает только в установленном приложении"); return }
        if case .installing = state { return }
        guard let base else {
            if !quiet { state = .failed("не указан адрес сервера дома") }
            return
        }
        if !quiet { state = .checking }
        do {
            var req = URLRequest(url: base.appendingPathComponent("api/app-mac"))
            req.timeoutInterval = 5
            let (data, resp) = try await URLSession.shared.data(for: req)
            guard (resp as? HTTPURLResponse)?.statusCode == 200,
                  let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                if !quiet { state = .failed("сервер не ответил") }
                return
            }
            guard obj["available"] as? Bool == true, let build = obj["build"] as? Int else {
                state = .upToDate
                return
            }
            let path = obj["url"] as? String ?? "/app-mac.zip"
            guard let url = URL(string: path, relativeTo: base)?.absoluteURL else { return }
            if build > Self.currentBuild {
                let info = Info(build: build, version: obj["version"] as? String ?? "?", url: url)
                state = .available(info)
                if auto { await install(info) }
            } else {
                state = .upToDate
            }
        } catch {
            if !quiet { state = .failed("сервер не отвечает") }
        }
    }

    func install(_ info: Info) async {
        if case .installing = state { return }
        let app = Bundle.main.bundleURL
        if app.path.contains("AppTranslocation") {
            state = .failed("Перенесите приложение в «Программы» и запустите оттуда — из «Загрузок» заменить его нельзя")
            return
        }
        guard FileManager.default.isWritableFile(atPath: app.deletingLastPathComponent().path) else {
            state = .failed("Нет прав на замену приложения. Перенесите его в «Программы» или обновите вручную")
            return
        }
        state = .installing
        do {
            let (tmp, resp) = try await URLSession.shared.download(from: info.url)
            guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw UpdateError("сервер ответил не так, как ожидалось") }
            let work = FileManager.default.temporaryDirectory.appendingPathComponent("hh-update-\(UUID().uuidString)")
            try FileManager.default.createDirectory(at: work, withIntermediateDirectories: true)
            let zip = work.appendingPathComponent("app.zip")
            try FileManager.default.moveItem(at: tmp, to: zip)
            let out = work.appendingPathComponent("out")
            try await Self.run("/usr/bin/ditto", ["-x", "-k", zip.path, out.path])
            let items = try FileManager.default.contentsOfDirectory(at: out, includingPropertiesForKeys: nil)
            guard let fresh = items.first(where: { $0.pathExtension == "app" }),
                  let plist = NSDictionary(contentsOf: fresh.appendingPathComponent("Contents/Info.plist")),
                  plist["CFBundleIdentifier"] as? String == Bundle.main.bundleIdentifier else {
                throw UpdateError("в архиве не то приложение")
            }
            let script = work.appendingPathComponent("swap.sh")
            let text = """
            #!/bin/bash
            PID="$1"; NEW="$2"; OLD="$3"
            while kill -0 "$PID" 2>/dev/null; do sleep 0.3; done
            rm -rf "$OLD.old"
            if mv "$OLD" "$OLD.old" && mv "$NEW" "$OLD"; then rm -rf "$OLD.old"; else mv "$OLD.old" "$OLD" 2>/dev/null; fi
            xattr -dr com.apple.quarantine "$OLD" 2>/dev/null
            open "$OLD"
            rm -rf "\(work.path)"
            """
            try text.write(to: script, atomically: true, encoding: .utf8)
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/bin/bash")
            p.arguments = ["-c", "nohup /bin/bash '\(script.path)' \(ProcessInfo.processInfo.processIdentifier) '\(fresh.path)' '\(app.path)' >/dev/null 2>&1 &"]
            try p.run()
            p.waitUntilExit()
            try? await Task.sleep(nanoseconds: 500_000_000)
            NSApp.terminate(nil)
        } catch {
            state = .failed((error as? UpdateError)?.text ?? error.localizedDescription)
        }
    }

    private struct UpdateError: Error { let text: String; init(_ t: String) { text = t } }

    private static func run(_ path: String, _ args: [String]) async throws {
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            let p = Process()
            p.executableURL = URL(fileURLWithPath: path)
            p.arguments = args
            p.terminationHandler = { proc in
                if proc.terminationStatus == 0 { cont.resume() }
                else { cont.resume(throwing: UpdateError("не удалось распаковать архив")) }
            }
            do { try p.run() } catch { cont.resume(throwing: error) }
        }
    }

    var statusText: String {
        switch state {
        case .idle: return "Версия \(Self.currentVersion) (сборка \(Self.currentBuild))"
        case .checking: return "Проверяю…"
        case .upToDate: return "Установлена последняя версия (сборка \(Self.currentBuild))"
        case .available(let i): return "Доступна сборка \(i.build) (версия \(i.version))"
        case .installing: return "Устанавливаю обновление…"
        case .failed(let m): return m
        }
    }
}
