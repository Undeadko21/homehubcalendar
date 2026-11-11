import SwiftUI
import AppKit
import HomeHubCore

/// Виджет на рабочем столе: окно без рамки под всеми окнами, на всех рабочих столах.
/// Размер — пресеты или произвольно (тянуть за край), положение запоминается.
enum WidgetSize: String, CaseIterable, Identifiable {
    case small, medium, large, wide
    var id: String { rawValue }
    var title: String {
        switch self { case .small: return "Маленький"; case .medium: return "Средний"; case .large: return "Большой"; case .wide: return "Две колонки" }
    }
    var size: NSSize {
        switch self {
        case .small: return NSSize(width: 230, height: 170)
        case .medium: return NSSize(width: 340, height: 250)
        case .large: return NSSize(width: 340, height: 460)
        case .wide: return NSSize(width: 560, height: 300)
        }
    }
}

extension Notification.Name {
    static let widgetResize = Notification.Name("hh.widget.resize")
}

struct DesktopWidgetView: View {
    /// Тесты рисуют виджет в картинку (ImageRenderer): окно-обёртка NSViewRepresentable там не рисуется, поэтому её отключают.
    static var rendering = false
    @ObservedObject var model: AppModel
    @AppStorage("widget.scale") private var scale = 1.0
    @AppStorage("widget.opacity") private var opacity = 0.85
    @AppStorage("widget.details") private var details = true
    @Environment(\.openWindow) private var openWindow

    @Environment(\.colorScheme) private var scheme

    private var head: String {
        let f = DateFormatter(); f.locale = Locale(identifier: "ru_RU"); f.dateFormat = "EEEE, d MMMM"
        let s = f.string(from: model.now)
        return s.prefix(1).uppercased() + s.dropFirst()
    }

    /// События выбранных людей на день: сначала весь день, затем по времени; закончившиеся сегодня не показываем.
    private func items(on day: Date) -> [(e: Event, start: Date?, end: Date?)] {
        let cal = Calendar.current
        let pick = model.menuPeople
        let all = (model.snapshot?.events ?? []).filter { pick.isEmpty || !pick.isDisjoint(with: $0.people) }
        let out: [(e: Event, start: Date?, end: Date?)] = all.compactMap { e in
            guard let s = DateParse.parse(e.start), cal.isDate(s, inSameDayAs: day) else { return nil }
            let en = DateParse.parse(e.end)
            if !e.allDay, cal.isDateInToday(day), let en, max(s, en) < model.now { return nil }
            return (e, e.allDay ? nil : s, e.allDay ? nil : en)
        }
        return out.sorted { l, r in
            if (l.start == nil) != (r.start == nil) { return l.start == nil }
            return (l.start ?? .distantPast) < (r.start ?? .distantPast)
        }
    }

    var body: some View {
        GeometryReader { geo in
            let compact = geo.size.height < 140
            let twoCols = geo.size.width >= 420
            let cal = Calendar.current
            let today = model.now
            let tomorrow = cal.date(byAdding: .day, value: 1, to: today) ?? today
            VStack(alignment: .leading, spacing: 6) {
                if !compact {
                    HStack {
                        Text(head).font(.system(size: 14 * scale, weight: .bold)).foregroundStyle(.red)
                        Spacer()
                        if model.source == .cache { Image(systemName: "wifi.slash").font(.caption).foregroundStyle(.secondary) }
                    }
                }
                if !model.configured {
                    Spacer()
                    Text("Подключите календарь в настройках")
                        .font(.system(size: 13 * scale)).foregroundStyle(.secondary).frame(maxWidth: .infinity)
                    Spacer()
                } else if twoCols {
                    HStack(alignment: .top, spacing: 12) {
                        column(today, height: geo.size.height, compact: compact, wide: true)
                        column(tomorrow, height: geo.size.height, compact: compact, wide: true)
                    }
                } else {
                    // Узкий виджет: сегодня, а если день закончился — завтра.
                    let day = items(on: today).isEmpty ? tomorrow : today
                    column(day, height: geo.size.height, compact: compact, wide: geo.size.width > 260)
                }
            }
            .padding(compact ? 8 : 14)
            .frame(width: geo.size.width, height: geo.size.height, alignment: .topLeading)
        }
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(.regularMaterial)
                .opacity(opacity)
        )
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .background { if !DesktopWidgetView.rendering { WidgetWindowConfigurator() } }
        .onTapGesture(count: 2) { NSApp.activate(ignoringOtherApps: true); openWindow(id: "main") }
        .contextMenu {
            Button("Обновить") { Task { await model.refresh() } }
            Menu("Размер") {
                ForEach(WidgetSize.allCases) { s in
                    Button(s.title) { NotificationCenter.default.post(name: .widgetResize, object: s) }
                }
            }
            Button("Открыть календарь") { NSApp.activate(ignoringOtherApps: true); openWindow(id: "main") }
            Divider()
            Button("Скрыть виджет") {
                UserDefaults.standard.set(false, forKey: "widget.on")
                NSApp.windows.first { $0.identifier?.rawValue == "hh-widget" }?.close()
            }
        }
    }

    /// Колонка дня: заголовок («СЕГОДНЯ» + число) и плашки событий.
    private func column(_ day: Date, height: CGFloat, compact: Bool, wide: Bool) -> some View {
        let list = items(on: day)
        let rowH = 40.0 * scale
        let room = max(1, Int((height - (compact ? 40 : 96)) / rowH))
        return VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 5) {
                Text(columnTitle(day, today: model.now)).font(.system(size: 10.5 * scale, weight: .bold)).foregroundStyle(.secondary)
                Text(dayNumber(day)).font(.system(size: 20 * scale, weight: .semibold, design: .rounded))
                    .foregroundStyle(Calendar.current.isDateInToday(day) ? Color.red : Color.primary)
            }
            if list.isEmpty {
                Text("Событий нет").font(.system(size: 12 * scale)).foregroundStyle(.secondary).padding(.top, 2)
            } else {
                ForEach(Array(list.prefix(room).enumerated()), id: \.offset) { _, it in
                    chip(it.e, start: it.start, end: it.end, wide: wide)
                }
                if list.count > room {
                    Text("ещё \(list.count - room)").font(.system(size: 11 * scale)).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

    /// Плашка как в виджете iPhone: тонированная заливка, цветная полоса слева, название и время цветом календаря.
    private func chip(_ e: Event, start: Date?, end: Date?, wide: Bool) -> some View {
        let who = e.people.compactMap { id in model.people.first { $0.id == id } }
        let hex = e.color ?? who.first?.color
        let isNow = start.map { $0 <= model.now && model.now < (end ?? $0) } ?? false
        let c = chipColors(hex, dark: scheme == .dark, strong: isNow)
        let f = DateFormatter(); f.dateFormat = "HH:mm"
        let time = start.map { s in f.string(from: s) + (end.map { " — " + f.string(from: $0) } ?? "") } ?? "весь день"
        let sub = ([who.map { $0.name }.joined(separator: ", ")] + [e.location ?? ""]).filter { !$0.isEmpty }.joined(separator: " · ")
        return HStack(spacing: 0) {
            Capsule().fill(c.bar).frame(width: 3).padding(.vertical, 3).padding(.leading, 3)
            VStack(alignment: .leading, spacing: 0) {
                Text(e.title).font(.system(size: 13 * scale, weight: .semibold)).lineLimit(1)
                Text(time).font(.system(size: 11.5 * scale)).opacity(0.85).lineLimit(1)
                if details && wide && !sub.isEmpty {
                    Text(sub).font(.system(size: 10.5 * scale)).opacity(0.7).lineLimit(1)
                }
            }
            .padding(.horizontal, 6).padding(.vertical, 3)
            Spacer(minLength: 0)
        }
        .foregroundStyle(c.text)
        .background(c.fill)
        .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
        .fixedSize(horizontal: false, vertical: true)
    }
}

/// Превращает окно SwiftUI в виджет: без заголовка, прозрачное, на уровне рабочего стола, на всех рабочих столах.
struct WidgetWindowConfigurator: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let v = NSView()
        DispatchQueue.main.async { [weak v] in
            guard let w = v?.window else { return }
            configure(w)
            context.coordinator.observe(w)
        }
        return v
    }
    func updateNSView(_ nsView: NSView, context: Context) {}
    func makeCoordinator() -> Coordinator { Coordinator() }

    private func configure(_ w: NSWindow) {
        w.identifier = NSUserInterfaceItemIdentifier("hh-widget")
        w.titleVisibility = .hidden
        w.titlebarAppearsTransparent = true
        w.styleMask.insert(.fullSizeContentView)
        w.styleMask.insert(.resizable)
        [NSWindow.ButtonType.closeButton, .miniaturizeButton, .zoomButton].forEach { w.standardWindowButton($0)?.isHidden = true }
        w.isOpaque = false
        w.backgroundColor = .clear
        w.hasShadow = false
        w.isMovableByWindowBackground = true
        w.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.desktopIconWindow)) + 1)
        w.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle, .fullScreenNone]
        w.minSize = NSSize(width: 150, height: 90)
        w.setFrameAutosaveName("HomeHubDesktopWidget")
        if w.frame.width < 150 { w.setContentSize(WidgetSize.medium.size) }
    }

    final class Coordinator {
        private var token: NSObjectProtocol?
        func observe(_ w: NSWindow) {
            token = NotificationCenter.default.addObserver(forName: .widgetResize, object: nil, queue: .main) { [weak w] note in
                guard let w, let s = note.object as? WidgetSize else { return }
                var f = w.frame
                let top = f.maxY
                f.size = s.size
                f.origin.y = top - f.size.height   // верхний край остаётся на месте
                w.setFrame(f, display: true, animate: true)
            }
        }
        deinit { if let t = token { NotificationCenter.default.removeObserver(t) } }
    }
}

/// Цвета плашки как у Apple (те же, что в виджете iPhone).
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

func dayNumber(_ d: Date) -> String { String(Calendar.current.component(.day, from: d)) }

/// «СЕГОДНЯ», «ЗАВТРА» или день недели.
func columnTitle(_ d: Date, today: Date) -> String {
    let cal = Calendar.current
    if cal.isDate(d, inSameDayAs: today) { return "СЕГОДНЯ" }
    if let t = cal.date(byAdding: .day, value: 1, to: today), cal.isDate(d, inSameDayAs: t) { return "ЗАВТРА" }
    let f = DateFormatter(); f.locale = Locale(identifier: "ru_RU"); f.dateFormat = "EEEE"
    return f.string(from: d).uppercased()
}
