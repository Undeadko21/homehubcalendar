import WidgetKit
import SwiftUI
import AppIntents

// Виджет «Календарь» для экрана «Домой». Настройки у каждого виджета свои (как на Android):
// адрес сервера и/или код подключения, дни, подробности, размер текста, прозрачность фона, люди.
// Данные виджет берёт сам: дома — /api/widget сервера, вне дома — зашифрованный снимок с Яндекс.Диска.
// (Общего хранилища с приложением нет: на бесплатном Apple ID App Groups ненадёжны.)

struct CalendarIntent: WidgetConfigurationIntent {
    static var title: LocalizedStringResource = "Календарь"
    static var description = IntentDescription("Ближайшие события семьи")

    @Parameter(title: "Адрес сервера", description: "Дома, например 192.168.1.50:8080")
    var server: String?

    @Parameter(title: "Код подключения", description: "Для связи вне дома (начинается с hhc1.)")
    var code: String?

    @Parameter(title: "Дней (1–3)", default: 2)
    var days: Int

    @Parameter(title: "Подробности (кто и где)", default: true)
    var details: Bool

    @Parameter(title: "Размер текста, %", default: 100)
    var scale: Int

    @Parameter(title: "Непрозрачность фона, %", default: 100)
    var opacity: Int

    @Parameter(title: "Люди", description: "Имена через запятую; пусто — все")
    var people: String?

    init() {}
}

// MARK: - Данные

struct WEvent: Identifiable {
    let id: String
    let start: Date?
    let end: Date?
    let allDay: Bool
    let time: String
    let title: String
    let who: String
    let note: String
    let location: String
    let color: String?
    let names: [String]
}

struct WDay {
    let label: String
    let date: Date
    var events: [WEvent]
}

struct WData {
    var days: [WDay] = []
    var birthday: String?
    var offline = false
    var message: String?
}

struct SrvPerson: Decodable { let name: String?; let color: String? }
struct SrvEvent: Decodable {
    let id: String
    let title: String
    let time: String?
    let start: String?
    let end: String?
    let all_day: Bool?
    let location: String?
    let who: String?
    let note: String?
    let colors: [String]?
    let people: [String]?
}
struct SrvDay: Decodable { let date: String; let label: String; let events: [SrvEvent] }
struct SrvBirthday: Decodable { let text: String }
struct SrvWidget: Decodable {
    let people: [String: SrvPerson]?
    let days: [SrvDay]
    let birthdays: [SrvBirthday]?
}

enum Loader {
    static func base(_ s: String?) -> URL? {
        var t = (s ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if t.isEmpty { return nil }
        if !t.contains("://") { t = "http://" + t }
        return URL(string: t)
    }

    static func load(_ c: CalendarIntent, now: Date) async -> WData {
        let days = max(1, min(3, c.days))
        let wanted = (c.people ?? "").split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces).lowercased() }.filter { !$0.isEmpty }
        var problems: [String] = []

        if let b = base(c.server) {
            do {
                var comps = URLComponents(url: b.appendingPathComponent("api/widget"), resolvingAgainstBaseURL: false)!
                comps.queryItems = [URLQueryItem(name: "days", value: String(days))]
                var req = URLRequest(url: comps.url!)
                req.timeoutInterval = 5
                let (data, resp) = try await URLSession.shared.data(for: req)
                let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
                if code == 401 { throw NSError(domain: "pin", code: 401) }
                guard code == 200 else { throw NSError(domain: "http", code: code) }
                let w = try JSONDecoder().decode(SrvWidget.self, from: data)
                return fromServer(w, wanted: wanted)
            } catch {
                problems.append("сервер не отвечает")
            }
        }
        if let cc = Cloud.parse(c.code ?? "") {
            do {
                let plain = try await Cloud.fetch(cc)
                let snap = try Snapshot.decode(plain)
                var d = fromSnapshot(snap, now: now, days: days, wanted: wanted)
                d.offline = true
                return d
            } catch {
                problems.append("облако: \((error as? LocalizedError)?.errorDescription ?? "нет связи")")
            }
        }
        if problems.isEmpty {
            return WData(message: "Нажмите и удерживайте виджет → «Изменить виджет», введите адрес сервера или код подключения")
        }
        return WData(message: "Нет связи (" + problems.joined(separator: "; ") + ")")
    }

    static func match(_ names: [String], _ wanted: [String]) -> Bool {
        wanted.isEmpty || names.contains { n in wanted.contains { n.lowercased().hasPrefix($0) || $0.hasPrefix(n.lowercased()) } }
    }

    static func fromServer(_ w: SrvWidget, wanted: [String]) -> WData {
        var out = WData()
        for d in w.days {
            let date = DateParse.parse(d.date) ?? Date()
            var evs: [WEvent] = []
            for e in d.events {
                let names = (e.people ?? []).compactMap { w.people?[$0]?.name }
                if !match(names, wanted) && !wanted.isEmpty { continue }
                evs.append(WEvent(id: d.date + e.id, start: e.start.flatMap { DateParse.parse($0) }, end: e.end.flatMap { DateParse.parse($0) },
                                  allDay: e.all_day ?? false, time: e.time ?? "", title: e.title, who: e.who ?? "", note: e.note ?? "",
                                  location: e.location ?? "", color: e.colors?.first, names: names))
            }
            out.days.append(WDay(label: d.label, date: date, events: evs))
        }
        out.birthday = w.birthdays?.first?.text
        return out
    }

    static func dayLabel(_ d: Date, today: Date, cal: Calendar) -> String {
        if cal.isDate(d, inSameDayAs: today) { return "Сегодня" }
        let f = DateFormatter()
        f.locale = Locale(identifier: "ru_RU")
        f.dateFormat = "EEEE, d MMMM"
        let s = f.string(from: d)
        let cap = s.prefix(1).uppercased() + s.dropFirst()
        if let t = cal.date(byAdding: .day, value: 1, to: today), cal.isDate(d, inSameDayAs: t) { return "Завтра, " + s }
        return cap
    }

    static func fromSnapshot(_ snap: Snapshot, now: Date, days: Int, wanted: [String]) -> WData {
        let cal = Calendar.current
        let today0 = cal.startOfDay(for: now)
        var people: [String: Person] = [:]
        for p in snap.people { people[p.id] = p }
        let hm = DateFormatter()
        hm.locale = Locale(identifier: "ru_RU")
        hm.dateFormat = "HH:mm"
        var out = WData()
        for i in 0..<days {
            guard let d0 = cal.date(byAdding: .day, value: i, to: today0), let d1 = cal.date(byAdding: .day, value: 1, to: d0) else { continue }
            var evs: [WEvent] = []
            for e in snap.events {
                guard let s = DateParse.parse(e.start) else { continue }
                var en = DateParse.parse(e.end) ?? s
                if e.allDay && en <= s { en = cal.date(byAdding: .day, value: 1, to: s) ?? s }
                let names = e.people.compactMap { people[$0]?.name }
                if !match(names, wanted) { continue }
                guard s < d1, en > d0 || (en == s && s >= d0) else { continue }
                if i == 0 && !e.allDay && en <= now { continue }
                let time = e.allDay ? "весь день" : "\(hm.string(from: s))–\(hm.string(from: en))"
                let who = e.people.compactMap { people[$0] }.map { ($0.emoji ?? "").isEmpty ? $0.name : "\($0.emoji!) \($0.name)" }.joined(separator: ", ")
                let color = e.people.compactMap { people[$0]?.color }.first
                evs.append(WEvent(id: "\(i)-\(e.id)", start: s, end: en, allDay: e.allDay, time: time, title: e.title, who: who,
                                  note: e.duty != nil ? "поездка" : "", location: e.location ?? "", color: color, names: names))
            }
            evs.sort { ($0.allDay ? 0 : 1, $0.start ?? d0) < ($1.allDay ? 0 : 1, $1.start ?? d0) }
            out.days.append(WDay(label: dayLabel(d0, today: today0, cal: cal), date: d0, events: evs))
        }
        return out
    }
}

// MARK: - Лента

struct CalendarEntry: TimelineEntry {
    let date: Date
    let data: WData
    let scale: Double
    let opacity: Double
    let details: Bool
}

struct Provider: AppIntentTimelineProvider {
    func placeholder(in context: Context) -> CalendarEntry {
        CalendarEntry(date: Date(), data: WData(message: "Календарь"), scale: 1, opacity: 1, details: true)
    }

    func snapshot(for configuration: CalendarIntent, in context: Context) async -> CalendarEntry {
        await entry(configuration, at: Date())
    }

    func timeline(for configuration: CalendarIntent, in context: Context) async -> Timeline<CalendarEntry> {
        let now = Date()
        let first = await entry(configuration, at: now)
        // Данные грузим раз в 15 минут, а «прошло/сейчас» пересчитываем каждые 5 минут без сети.
        var entries = [first]
        for k in 1...2 {
            entries.append(CalendarEntry(date: now.addingTimeInterval(Double(k) * 300), data: first.data,
                                         scale: first.scale, opacity: first.opacity, details: first.details))
        }
        return Timeline(entries: entries, policy: .after(now.addingTimeInterval(900)))
    }

    private func entry(_ c: CalendarIntent, at date: Date) async -> CalendarEntry {
        let data = await Loader.load(c, now: date)
        return CalendarEntry(date: date, data: data, scale: Double(max(70, min(160, c.scale))) / 100,
                             opacity: Double(max(0, min(100, c.opacity))) / 100, details: c.details)
    }
}

// MARK: - Вид

func hexColor(_ hex: String?) -> Color {
    guard let h = hex?.trimmingCharacters(in: CharacterSet(charactersIn: "#")), h.count == 6, let v = UInt32(h, radix: 16) else { return .gray }
    return Color(red: Double((v >> 16) & 255) / 255, green: Double((v >> 8) & 255) / 255, blue: Double(v & 255) / 255)
}

enum Row: Identifiable {
    case day(String, Int)
    case event(WEvent)
    var id: String {
        switch self { case .day(let s, let i): return "d\(i)\(s)"; case .event(let e): return e.id }
    }
}

struct WidgetView: View {
    let entry: CalendarEntry
    @Environment(\.widgetFamily) private var family

    private var capacity: Int {
        let base: Double
        switch family {
        case .systemSmall: base = 3
        case .systemMedium: base = 4
        default: base = 9
        }
        return max(1, Int(base / entry.scale))
    }

    private var head: String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "ru_RU")
        f.dateFormat = "EEEE, d MMMM"
        let s = f.string(from: entry.date)
        return s.prefix(1).uppercased() + s.dropFirst()
    }

    private var rows: [Row] {
        var out: [Row] = []
        for (i, d) in entry.data.days.enumerated() {
            let evs = d.events.filter { e in
                if e.allDay { return true }
                guard let end = e.end else { return true }
                return i > 0 || end > entry.date   // прошедшее сегодня скрываем
            }
            if evs.isEmpty { continue }
            if i > 0 || entry.data.days.count > 1 { out.append(.day(d.label, i)) }
            out.append(contentsOf: evs.map { Row.event($0) })
        }
        return out
    }

    var body: some View {
        let list = Array(rows.prefix(capacity))
        VStack(alignment: .leading, spacing: 4 * entry.scale) {
            if family != .systemSmall {
                HStack {
                    Text(head).font(.system(size: 14 * entry.scale, weight: .bold)).foregroundStyle(.red)
                    Spacer()
                    if entry.data.offline { Image(systemName: "icloud").font(.caption2).foregroundStyle(.secondary) }
                }
                if family == .systemLarge, let b = entry.data.birthday {
                    Text(b).font(.system(size: 11 * entry.scale)).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            if let m = entry.data.message {
                Text(m).font(.system(size: 12 * entry.scale)).foregroundStyle(.secondary)
            } else if list.isEmpty {
                Text("Ближайших событий нет").font(.system(size: 13 * entry.scale)).foregroundStyle(.secondary)
            } else {
                ForEach(list) { row in
                    switch row {
                    case .day(let s, _):
                        Text(s).font(.system(size: 11 * entry.scale, weight: .semibold)).foregroundStyle(.secondary).padding(.top, 2)
                    case .event(let e):
                        EventLine(e: e, scale: entry.scale, details: entry.details, now: entry.date)
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .padding(family == .systemSmall ? 12 : 14)
        .padding(family == .systemSmall ? 12 : 14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .containerBackground(Color(.systemBackground).opacity(entry.opacity), for: .widget)
    }
}

struct EventLine: View {
    let e: WEvent
    let scale: Double
    let details: Bool
    let now: Date

    private var isNow: Bool {
        guard !e.allDay, let s = e.start, let en = e.end else { return false }
        return s <= now && now < en
    }

    private var sub: String {
        [e.who, e.note, e.location].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    var body: some View {
        HStack(alignment: .top, spacing: 6) {
            RoundedRectangle(cornerRadius: 2).fill(hexColor(e.color)).frame(width: 3)
            VStack(alignment: .leading, spacing: 0) {
                Text(e.title).font(.system(size: 13 * scale, weight: .semibold)).lineLimit(1)
                Text(isNow ? "сейчас · " + e.time : e.time)
                    .font(.system(size: 11 * scale)).foregroundStyle(isNow ? Color.red : Color.secondary).lineLimit(1)
                if details && !sub.isEmpty {
                    Text(sub).font(.system(size: 11 * scale)).foregroundStyle(.secondary).lineLimit(1)
                }
            }
        }
        .fixedSize(horizontal: false, vertical: true)
    }
}

@main
struct CalendarWidget: Widget {
    var body: some WidgetConfiguration {
        AppIntentConfiguration(kind: "HomeHubCalendarWidget", intent: CalendarIntent.self, provider: Provider()) { entry in
            WidgetView(entry: entry)
        }
        .configurationDisplayName("Календарь")
        .description("Ближайшие события семьи. Адрес сервера или код подключения задаются в настройках виджета.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
        .contentMarginsDisabled()
    }
}
