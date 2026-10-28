import Foundation
import SwiftUI
import WebKit
#if os(macOS)
import AppKit
#else
import UIKit
#endif
#if canImport(HomeHubCore)
import HomeHubCore
#endif

enum AppError: LocalizedError {
    case pin, http(Int)
    var errorDescription: String? {
        switch self {
        case .pin: return "нужен PIN: войдите в окне календаря"
        case .http(let c): return "ответ \(c)"
        }
    }
}

@MainActor
final class AppModel: ObservableObject {
    enum Source { case none, server, cloud, cache }

    private let defaults = UserDefaults.standard

    @Published var serverURL: String { didSet { defaults.set(serverURL, forKey: "serverURL"); failures = 0; Task { await refresh() } } }
    @Published var code: String { didSet { defaults.set(code, forKey: "cloudCode"); Task { await refresh() } } }
    @Published var menuPeople: Set<String> { didSet { defaults.set(Array(menuPeople), forKey: "menuPeople") } }
    @Published var tripPeople: Set<String> { didSet { defaults.set(Array(tripPeople), forKey: "tripPeople"); reschedule() } }
    @Published var notify: Bool { didSet { defaults.set(notify, forKey: "notify"); if notify { Notifier.requestAuthorization() }; reschedule() } }
    @Published var lead: Int { didSet { defaults.set(lead, forKey: "lead"); reschedule() } }

    @Published private(set) var snapshot: Snapshot?
    @Published private(set) var source: Source = .none
    @Published private(set) var lastUpdate: Date?
    @Published private(set) var error: String?
    @Published private(set) var now = Date()
    @Published private(set) var webOK = false
    @Published var reloadToken = 0

    private var failures = 0
    private var busy = false

    init() {
        serverURL = defaults.string(forKey: "serverURL") ?? ""
        code = defaults.string(forKey: "cloudCode") ?? ""
        menuPeople = Set(defaults.stringArray(forKey: "menuPeople") ?? [])
        tripPeople = Set(defaults.stringArray(forKey: "tripPeople") ?? [])
        notify = defaults.object(forKey: "notify") as? Bool ?? true
        lead = defaults.object(forKey: "lead") as? Int ?? 30
        if let data = try? Data(contentsOf: Self.cacheURL), let snap = try? Snapshot.decode(data) {
            snapshot = snap
            source = .cache
        }
        start()
    }

    private func start() {
        Task { await loop() }
        #if os(macOS)
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            guard let model = self else { return }
            Task { @MainActor in await model.refresh() }
        }
        #endif
    }

    // MARK: - Состояние

    var serverBase: URL? {
        var s = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.isEmpty { return nil }
        if !s.contains("://") { s = "http://" + s }
        return URL(string: s)
    }

    var configured: Bool { serverBase != nil || Cloud.parse(code) != nil }
    var people: [Person] { snapshot?.people ?? [] }

    var upcoming: [AgendaItem] {
        Agenda.upcoming(snapshot?.events ?? [], people: menuPeople, now: now)
    }

    var menuTitle: String { Agenda.menuTitle(upcoming.first, now: now) }

    var statusText: String {
        let t = lastUpdate.map { Self.time.string(from: $0) } ?? ""
        switch source {
        case .server: return "Сервер дома · \(t)"
        case .cloud: return "Через облако · \(t)"
        case .cache: return "Нет связи, показан последний снимок"
        case .none: return configured ? "Загружаю…" : "Не подключено"
        }
    }

    static let time: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "ru_RU")
        f.dateFormat = "HH:mm"
        return f
    }()

    // MARK: - Обновление

    private func loop() async {
        var tick = 0
        while !Task.isCancelled {
            if tick % 2 == 0 { await refresh() } else { now = Date() }
            tick += 1
            try? await Task.sleep(nanoseconds: 30_000_000_000)
        }
    }

    func refresh() async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        now = Date()
        var problems: [String] = []
        if let base = serverBase {
            do {
                let data = try await fetchServer(base)
                try accept(data, from: .server)
                failures = 0
                webOK = true
                return
            } catch {
                failures += 1
                if failures >= 2 { webOK = false }
                problems.append("Сервер: \(describe(error))")
            }
        } else {
            webOK = false
        }
        if let c = Cloud.parse(code) {
            do {
                let plain = try await Cloud.fetch(c)
                try accept(plain, from: .cloud)
                self.error = nil
                return
            } catch {
                problems.append("Облако: \(describe(error))")
            }
        }
        self.error = problems.isEmpty ? nil : problems.joined(separator: "\n")
        if snapshot != nil { source = .cache }
    }

    private func fetchServer(_ base: URL) async throws -> Data {
        var req = URLRequest(url: base.appendingPathComponent("api/snapshot"))
        req.timeoutInterval = 3
        var (data, resp) = try await URLSession.shared.data(for: req)
        if (resp as? HTTPURLResponse)?.statusCode == 401 {
            await copyWebCookies()  // вход по PIN сделан в окне календаря — переносим куки
            (data, resp) = try await URLSession.shared.data(for: req)
        }
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if code == 401 { throw AppError.pin }
        guard code == 200 else { throw AppError.http(code) }
        return data
    }

    private func copyWebCookies() async {
        let cookies: [HTTPCookie] = await withCheckedContinuation { cont in
            WKWebsiteDataStore.default().httpCookieStore.getAllCookies { cont.resume(returning: $0) }
        }
        for c in cookies { HTTPCookieStorage.shared.setCookie(c) }
    }

    private func accept(_ data: Data, from s: Source) throws {
        let snap = try Snapshot.decode(data)
        snapshot = snap
        source = s
        lastUpdate = Date()
        error = nil
        try? FileManager.default.createDirectory(at: Self.cacheURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: Self.cacheURL, options: .atomic)
        reschedule()
    }

    private func reschedule() {
        guard let snap = snapshot else { return }
        Notifier.schedule(snap, enabled: notify, tripPeople: tripPeople, lead: lead)
    }

    private func describe(_ error: Error) -> String {
        if let e = error as? URLError {
            switch e.code {
            case .timedOut: return "не отвечает"
            case .cannotConnectToHost, .cannotFindHost, .notConnectedToInternet, .networkConnectionLost: return "нет связи"
            default: break
            }
        }
        return error.localizedDescription
    }

    static var cacheURL: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSTemporaryDirectory())
        return base.appendingPathComponent("HomeHubCalendar/snapshot.json")
    }
}
