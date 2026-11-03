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
        let days = max(2, min(3, c.days))   // для среднего виджета нужен ещё и завтрашний день
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
                let color = e.color ?? e.people.compactMap { people[$0]?.color }.first
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

// MARK: - Вид (по образцу виджета «Календарь» от Apple)

func hexColor(_ hex: String?) -> Color {
    guard let h = hex?.trimmingCharacters(in: CharacterSet(charactersIn: "#")), h.count == 6, let v = UInt32(h, radix: 16) else { return .gray }
    return Color(red: Double((v >> 16) & 255) / 255, green: Double((v >> 8) & 255) / 255, blue: Double(v & 255) / 255)
}

/// Цвета плашки как у Apple: полупрозрачная заливка цвета календаря, полоса слева и текст того же цвета (в тёмной теме светлее).
func chipColors(_ hex: String?, dark: Bool, strong: Bool) -> (text: Color, fill: Color, bar: Color) {
    var r = 0.56, g = 0.56, b = 0.58
    if let h = hex?.trimmingCharacters(in: CharacterSet(charactersIn: "#")), h.count == 6, let v = UInt32(h, radix: 16) {
        r = Double((v >> 16) & 255) / 255; g = Double((v >> 8) & 255) / 255; b = Double(v & 255) / 255
    }
    let target = dark ? 1.0 : 0.0
    let k = dark ? 0.32 : 0.30
    let text = Color(red: r + (target - r) * k, green: g + (target - g) * k, blue: b + (target - b) * k)
    let base = Color(red: r, green: g, blue: b)
    return (text, base.opacity(dark ? (strong ? 0.34 : 0.22) : (strong ? 0.26 : 0.17)), base)
}

private let ruLocale = Locale(identifier: "ru_RU")

func upperWeekday(_ d: Date) -> String {
    let f = DateFormatter()
    f.locale = ruLocale
    f.dateFormat = "EEEE"
    return f.string(from: d).uppercased()
}

func dayNumber(_ d: Date) -> String { String(Calendar.current.component(.day, from: d)) }

/// «ЗАВТРА», «ВТОРНИК»… для заголовка не-сегодняшней колонки.
func columnTitle(_ d: Date, today: Date) -> String {
    let cal = Calendar.current
    if cal.isDate(d, inSameDayAs: today) { return "СЕГОДНЯ" }
    if let t = cal.date(byAdding: .day, value: 1, to: today), cal.isDate(d, inSameDayAs: t) { return "ЗАВТРА" }
    return upperWeekday(d)
}

struct WidgetView: View {
    let entry: CalendarEntry
    @Environment(\.widgetFamily) private var family

    private var s: Double { entry.scale }
    private var today: Date { entry.data.days.first?.date ?? Calendar.current.startOfDay(for: entry.date) }

    /// События дня без уже прошедших сегодня.
    private func events(_ i: Int) -> [WEvent] {
        guard i < entry.data.days.count else { return [] }
        return entry.data.days[i].events.filter { e in
            if e.allDay { return true }
            guard let end = e.end else { return true }
            return i > 0 || end > entry.date
        }
    }

    private func chips(_ list: [WEvent], limit: Int) -> some View {
        let shown = Array(list.prefix(limit))
        return VStack(alignment: .leading, spacing: 4 * s) {
            ForEach(shown) { e in
                EventChip(e: e, scale: s, details: showDetails, now: entry.date)
            }
            if list.count > shown.count {
                Text("ещё \(list.count - shown.count)").font(.system(size: 11 * s)).foregroundStyle(.secondary)
            }
        }
    }

    /// Сколько плашек влезает: высота плашки с подробностями ~52 pt, без них ~38 pt.
    private func fit(_ avail: Double) -> Int {
        let chipH = (showDetails ? 54.0 : 40.0) * s
        return max(1, Int((avail + 4 * s) / (chipH + 4 * s)))
    }

    private var showDetails: Bool { entry.details && family != .systemSmall }

    private struct PlanItem: Identifiable { let id: Int; let take: Int }

    /// Для большого виджета: какие дни и по сколько плашек помещается (высота ~330 pt).
    private var largePlan: [PlanItem] {
        var left = 330.0 - (entry.data.birthday != nil ? 18 : 0)
        var out: [PlanItem] = []
        for i in entry.data.days.indices {
            let n = events(i).count
            if n == 0 && i > 0 { continue }
            let head = (i == 0 ? 30.0 : 16.0) * s + 6 * s
            if left < head + (n > 0 ? 38 * s : 0) { break }
            let take = n == 0 ? 0 : min(n, fit(left - head))
            out.append(PlanItem(id: i, take: take))
            left -= head + Double(max(take, 1)) * ((showDetails ? 52.0 : 38.0) + 4) * s + 8 * s
        }
        return out
    }

    private var todayHeader: some View {
        VStack(alignment: .leading, spacing: -2 * s) {
            Text(upperWeekday(today)).font(.system(size: 11 * s, weight: .semibold)).foregroundStyle(.red).lineLimit(1)
            Text(dayNumber(today)).font(.system(size: 34 * s, weight: .regular)).lineLimit(1)
        }
    }

    private func smallHeader(_ i: Int) -> some View {
        let d = i < entry.data.days.count ? entry.data.days[i].date : today
        return Text(columnTitle(d, today: today)).font(.system(size: 11 * s, weight: .semibold)).foregroundStyle(.secondary).lineLimit(1)
    }

    private func empty(_ text: String = "Нет событий") -> some View {
        Text(text).font(.system(size: 13 * s)).foregroundStyle(.secondary)
    }

    private var column0: some View {
        VStack(alignment: .leading, spacing: 4 * s) {
            todayHeader
            let list = events(0)
            if list.isEmpty { empty() } else { chips(list, limit: fit(83)) }
        }
    }

    private var column1: some View {
        VStack(alignment: .leading, spacing: 6 * s) {
            smallHeader(1)
            let list = events(1)
            if list.isEmpty { empty() } else { chips(list, limit: fit(110)) }
        }
    }

    private var large: some View {
        VStack(alignment: .leading, spacing: 6 * s) {
            ForEach(largePlan) { item in
                let d = entry.data.days[item.id]
                let list = events(item.id)
                VStack(alignment: .leading, spacing: 4 * s) {
                    if item.id == 0 {
                        HStack(alignment: .firstTextBaseline, spacing: 6 * s) {
                            Text(upperWeekday(d.date)).font(.system(size: 11 * s, weight: .semibold)).foregroundStyle(.red)
                            Text(dayNumber(d.date)).font(.system(size: 22 * s, weight: .regular))
                        }
                    } else {
                        smallHeader(item.id)
                    }
                    if list.isEmpty { empty() } else { chips(list, limit: item.take) }
                }
            }
            if let b = entry.data.birthday {
                Text(b).font(.system(size: 11 * s)).foregroundStyle(.secondary).lineLimit(1)
            }
        }
    }

    var body: some View {
        Group {
            if let m = entry.data.message {
                VStack(alignment: .leading, spacing: 4 * s) {
                    if family != .systemSmall { smallHeader(0) }
                    Text(m).font(.system(size: 12 * s)).foregroundStyle(.secondary)
                }
            } else {
                switch family {
                case .systemSmall:
                    column0
                case .systemMedium:
                    HStack(alignment: .top, spacing: 14 * s) {
                        column0.frame(maxWidth: .infinity, alignment: .topLeading)
                        column1.frame(maxWidth: .infinity, alignment: .topLeading)
                    }
                default:
                    large
                }
            }
        }
        .padding(family == .systemSmall ? 12 : 14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .overlay(alignment: .topTrailing) {
            if entry.data.offline {
                Image(systemName: "icloud").font(.system(size: 10)).foregroundStyle(.secondary).padding(8)
            }
        }
        .containerBackground(Color(.systemBackground).opacity(entry.opacity), for: .widget)
    }
}

/// Плашка события в стиле Apple: тонированная заливка, цветная полоса слева, название и время цветом календаря.
struct EventChip: View {
    let e: WEvent
    let scale: Double
    let details: Bool
    let now: Date
    @Environment(\.colorScheme) private var scheme

    private var isNow: Bool {
        guard !e.allDay, let s = e.start, let en = e.end else { return false }
        return s <= now && now < en
    }

    private var timeText: String {
        e.allDay ? "" : e.time.replacingOccurrences(of: "–", with: " — ")
    }

    private var sub: String {
        [e.who, e.note, e.location].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    var body: some View {
        let c = chipColors(e.color, dark: scheme == .dark, strong: isNow)
        if e.allDay {
            // Событие на весь день — капсула со значком, как у Apple.
            HStack(spacing: 5 * scale) {
                ZStack {
                    Circle().fill(c.bar)
                    Image(systemName: "calendar").font(.system(size: 8 * scale, weight: .bold)).foregroundStyle(.white)
                }
                .frame(width: 16 * scale, height: 16 * scale)
                Text(e.title).font(.system(size: 14 * scale, weight: .semibold)).lineLimit(1)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 3 * scale)
            .padding(.vertical, 2 * scale)
            .foregroundStyle(c.text)
            .background(c.fill)
            .clipShape(Capsule())
        } else {
            HStack(spacing: 0) {
                // Полоса не доходит до краёв плашки и закруглена, как у Apple.
                Capsule().fill(c.bar).frame(width: 3).padding(.vertical, 3).padding(.leading, 3)
                VStack(alignment: .leading, spacing: 0) {
                    Text(e.title).font(.system(size: 15 * scale, weight: .semibold)).lineLimit(1)
                    if !timeText.isEmpty {
                        Text(timeText).font(.system(size: 13.5 * scale)).opacity(0.85).lineLimit(1)
                    }
                    if details && !sub.isEmpty {
                        Text(sub).font(.system(size: 11 * scale)).opacity(0.7).lineLimit(1)
                    }
                }
                .padding(.horizontal, 6)
                .padding(.vertical, 3)
                Spacer(minLength: 0)
            }
            .foregroundStyle(c.text)
            .background(c.fill)
            .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
            .fixedSize(horizontal: false, vertical: true)
        }
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
