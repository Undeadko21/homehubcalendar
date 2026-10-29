import SwiftUI
import AppKit
import HomeHubCore

/// Виджет на рабочем столе: окно без рамки под всеми окнами, на всех рабочих столах.
/// Размер — пресеты или произвольно (тянуть за край), положение запоминается.
enum WidgetSize: String, CaseIterable, Identifiable {
    case small, medium, large
    var id: String { rawValue }
    var title: String {
        switch self { case .small: return "Маленький"; case .medium: return "Средний"; case .large: return "Большой" }
    }
    var size: NSSize {
        switch self {
        case .small: return NSSize(width: 230, height: 170)
        case .medium: return NSSize(width: 340, height: 250)
        case .large: return NSSize(width: 340, height: 460)
        }
    }
}

extension Notification.Name {
    static let widgetResize = Notification.Name("hh.widget.resize")
}

struct DesktopWidgetView: View {
    @ObservedObject var model: AppModel
    @AppStorage("widget.scale") private var scale = 1.0
    @AppStorage("widget.opacity") private var opacity = 0.85
    @AppStorage("widget.details") private var details = true
    @Environment(\.openWindow) private var openWindow

    private func color(_ hex: String?) -> Color {
        guard let h = hex?.trimmingCharacters(in: CharacterSet(charactersIn: "#")), h.count == 6, let v = UInt32(h, radix: 16) else { return .gray }
        return Color(red: Double((v >> 16) & 255) / 255, green: Double((v >> 8) & 255) / 255, blue: Double(v & 255) / 255)
    }

    private var head: String {
        let f = DateFormatter(); f.locale = Locale(identifier: "ru_RU"); f.dateFormat = "EEEE, d MMMM"
        let s = f.string(from: model.now)
        return s.prefix(1).uppercased() + s.dropFirst()
    }

    var body: some View {
        GeometryReader { geo in
            let rowH = 40.0 * scale
            let compact = geo.size.height < 140
            let room = max(1, Int((geo.size.height - (compact ? 18 : 62)) / rowH))
            VStack(alignment: .leading, spacing: 6) {
                if !compact {
                    HStack {
                        Text(head).font(.system(size: 14 * scale, weight: .bold)).foregroundStyle(.red)
                        Spacer()
                        if model.source == .cache { Image(systemName: "wifi.slash").font(.caption).foregroundStyle(.secondary) }
                    }
                }
                if model.upcoming.isEmpty {
                    Spacer()
                    Text(model.configured ? "Ближайших событий нет" : "Подключите календарь в настройках")
                        .font(.system(size: 13 * scale)).foregroundStyle(.secondary).frame(maxWidth: .infinity)
                    Spacer()
                } else {
                    ForEach(model.upcoming.prefix(room)) { item in
                        row(item, wide: geo.size.width > 260)
                    }
                    Spacer(minLength: 0)
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
        .background(WidgetWindowConfigurator())
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

    private func row(_ item: AgendaItem, wide: Bool) -> some View {
        let who = item.event.people.compactMap { id in model.people.first { $0.id == id } }
        return HStack(alignment: .top, spacing: 8) {
            RoundedRectangle(cornerRadius: 2).fill(color(who.first?.color)).frame(width: 3)
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 6) {
                    Text(item.start <= model.now ? "сейчас" : Agenda.when(item.start, now: model.now))
                        .font(.system(size: 12 * scale, weight: .semibold, design: .rounded))
                        .foregroundStyle(item.start <= model.now ? Color.red : Color.secondary)
                    Text(item.event.title).font(.system(size: 13 * scale, weight: .semibold)).lineLimit(1)
                }
                if details && wide {
                    let sub = ([who.map { $0.name }.joined(separator: ", ")] + [item.event.location ?? ""]).filter { !$0.isEmpty }.joined(separator: " · ")
                    if !sub.isEmpty { Text(sub).font(.system(size: 11 * scale)).foregroundStyle(.secondary).lineLimit(1) }
                }
            }
            Spacer(minLength: 0)
        }
        .frame(minHeight: 30 * scale)
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
