import SwiftUI
import AppKit
import ServiceManagement
import HomeHubCore

// MARK: - Строка меню

struct MenuLabel: View {
    @ObservedObject var model: AppModel
    @Environment(\.openWindow) private var openWindow
    var body: some View {
        Group {
            if model.menuTitle.isEmpty {
                Image(systemName: "calendar")
            } else {
                Text(model.menuTitle)
            }
        }
        .task { await Updater.shared.loop(model) }
        .task {
            // Виджет на рабочем столе открывается при запуске, если он был включён.
            if UserDefaults.standard.bool(forKey: "widget.on") { openWindow(id: "widget") }
        }
    }
}

struct MenuView: View {
    @ObservedObject var model: AppModel
    @ObservedObject private var updater = Updater.shared
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if !model.configured {
                Text("Календарь не подключён").foregroundStyle(.secondary)
            } else if model.upcoming.isEmpty {
                Text("Ближайших событий нет").foregroundStyle(.secondary)
            } else {
                ForEach(model.upcoming.prefix(6)) { item in
                    ItemRow(item: item, model: model)
                }
            }
            if case .available(let info) = updater.state {
                Button("Обновить приложение до сборки \(info.build)") { Task { await updater.install(info) } }
            } else if case .installing = updater.state {
                Text("Устанавливаю обновление…").font(.caption).foregroundStyle(.secondary)
            }
            Divider()
            HStack {
                Button("Открыть календарь") { show("main") }
                Button("Настройки…") { show("settings") }.keyboardShortcut(",")
                Button("Виджет") { UserDefaults.standard.set(true, forKey: "widget.on"); openWindow(id: "widget") }
                Spacer()
                Button("Обновить") { Task { await model.refresh(); model.reloadToken += 1 } }
            }
            HStack {
                Text(model.statusText).font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("Выйти") { NSApplication.shared.terminate(nil) }.buttonStyle(.link).font(.caption)
            }
        }
        .padding(14)
        .frame(width: 340)
    }

    private func show(_ id: String) {
        openWindow(id: id)
        NSApp.activate(ignoringOtherApps: true)
    }
}

struct ItemRow: View {
    let item: AgendaItem
    @ObservedObject var model: AppModel

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(item.start <= model.now ? "сейчас" : Agenda.when(item.start, now: model.now))
                .font(.system(.callout, design: .rounded).weight(.semibold))
                .foregroundStyle(item.start <= model.now ? Color.red : Color.primary)
                .frame(width: 78, alignment: .leading)
            VStack(alignment: .leading, spacing: 1) {
                Text(item.event.title).lineLimit(2)
                let who = names
                if !who.isEmpty { Text(who).font(.caption).foregroundStyle(.secondary) }
            }
            Spacer(minLength: 0)
        }
    }

    private var names: String {
        item.event.people.compactMap { id in model.people.first { $0.id == id } }
            .map { ($0.emoji ?? "").isEmpty ? $0.name : "\($0.emoji!) \($0.name)" }
            .joined(separator: ", ")
    }
}

// MARK: - Главное окно

struct MainView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        Group {
            if !model.configured {
                ConnectView(model: model)
            } else if model.webOK, let url = model.serverBase {
                WebView(url: url, reloadToken: model.reloadToken)
            } else {
                OfflineView(model: model)
            }
        }
        .frame(minWidth: 460, minHeight: 560)
    }
}

/// Когда сервер дома не отвечает: события из последнего снимка (облачного или сохранённого).
struct OfflineView: View {
    @ObservedObject var model: AppModel

    private var days: [(Date, [AgendaItem])] {
        let cal = Calendar.current
        let end = cal.date(byAdding: .day, value: 8, to: cal.startOfDay(for: model.now)) ?? model.now
        let items = model.upcoming.filter { $0.start < end }
        let grouped = Dictionary(grouping: items) { cal.startOfDay(for: $0.start) }
        return grouped.keys.sorted().map { ($0, grouped[$0] ?? []) }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.statusText).font(.callout.weight(.semibold))
                    if let e = model.error { Text(e).font(.caption).foregroundStyle(.secondary) }
                }
                Spacer()
                Button("Повторить") { Task { await model.refresh() } }
            }
            .padding(12)
            Divider()
            if days.isEmpty {
                Spacer()
                Text("Ближайших событий нет").foregroundStyle(.secondary)
                Spacer()
            } else {
                List {
                    ForEach(days, id: \.0) { day, items in
                        Section(header: Text(Self.dayName(day, now: model.now))) {
                            ForEach(items) { ItemRow(item: $0, model: model) }
                        }
                    }
                }
            }
        }
    }

    static func dayName(_ d: Date, now: Date) -> String {
        let cal = Calendar.current
        if cal.isDate(d, inSameDayAs: now) { return "Сегодня" }
        if let t = cal.date(byAdding: .day, value: 1, to: now), cal.isDate(d, inSameDayAs: t) { return "Завтра" }
        let f = DateFormatter()
        f.locale = Locale(identifier: "ru_RU")
        f.dateFormat = "EEEE, d MMMM"
        return f.string(from: d).capitalized
    }
}

// MARK: - Подключение и настройки

struct ConnectView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "calendar").font(.system(size: 44)).foregroundStyle(.red)
            Text("Подключите календарь").font(.title2.weight(.semibold))
            Text("Укажите адрес сервера дома или вставьте код подключения (он показан в настройках календаря → Подключение → Облако). Можно и то и другое: дома приложение ходит на сервер, вне дома читает снимок из облака.")
                .multilineTextAlignment(.center).foregroundStyle(.secondary)
            SettingsForm(model: model, compact: true)
        }
        .padding(24)
    }
}

struct SettingsView: View {
    @ObservedObject var model: AppModel
    var body: some View {
        SettingsForm(model: model, compact: false).padding(8)
    }
}

struct SettingsForm: View {
    @ObservedObject var model: AppModel
    let compact: Bool
    @State private var login = (SMAppService.mainApp.status == .enabled)
    @ObservedObject private var updater = Updater.shared
    @Environment(\.openWindow) private var openWindow
    @AppStorage("widget.on") private var widgetOn = false
    @AppStorage("widget.scale") private var widgetScale = 1.0
    @AppStorage("widget.opacity") private var widgetOpacity = 0.85
    @AppStorage("widget.details") private var widgetDetails = true
    @State private var widgetSize = ""

    var body: some View {
        Form {
            Section("Подключение") {
                TextField("Сервер дома", text: $model.serverURL, prompt: Text("http://192.168.0.10:8080"))
                    .autocorrectionDisabled()
                TextField("Код подключения (вне дома)", text: $model.code, prompt: Text("hhc1.…"), axis: .vertical)
                    .lineLimit(1...3).autocorrectionDisabled()
                if !model.code.isEmpty && Cloud.parse(model.code) == nil {
                    Text("Код не распознан").font(.caption).foregroundStyle(.red)
                }
                HStack {
                    Text(model.statusText).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("Проверить") { Task { await model.refresh() } }
                }
                if let e = model.error { Text(e).font(.caption).foregroundStyle(.red) }
            }
            if !compact {
                if !model.people.isEmpty {
                    Section("Чьи события в строке меню") {
                        ForEach(model.people) { p in
                            Toggle(label(p), isOn: binding(for: p.id, in: \.menuPeople))
                        }
                        Text("Если никого не выбрано, показываются события всех.").font(.caption).foregroundStyle(.secondary)
                    }
                }
                Section("Уведомления") {
                    Toggle("Показывать уведомления", isOn: $model.notify)
                    if model.notify {
                        Stepper("Поездки: за \(model.lead) мин", value: $model.lead, in: 5...120, step: 5)
                        Text("Поездки и встречи. За сколько минут напоминать о встречах, задаётся для каждого человека в настройках календаря.")
                            .font(.caption).foregroundStyle(.secondary)
                        ForEach(model.people) { p in
                            Toggle("Напоминать: \(label(p))", isOn: binding(for: p.id, in: \.tripPeople))
                        }
                    }
                }
                Section("Виджет на рабочем столе") {
                    Toggle("Показывать при запуске", isOn: $widgetOn)
                    Picker("Размер", selection: $widgetSize) {
                        Text("—").tag("")
                        ForEach(WidgetSize.allCases) { Text($0.title).tag($0.rawValue) }
                    }
                    .onChange(of: widgetSize) { v in
                        if let s = WidgetSize(rawValue: v) { NotificationCenter.default.post(name: .widgetResize, object: s) }
                    }
                    HStack { Text("Текст"); Slider(value: $widgetScale, in: 0.8...1.5) }
                    HStack { Text("Фон"); Slider(value: $widgetOpacity, in: 0...1) }
                    Toggle("Подробности (кто и где)", isOn: $widgetDetails)
                    Text("Виджет можно двигать и растягивать за край. Двойной щелчок открывает календарь.")
                        .font(.caption).foregroundStyle(.secondary)
                    Button("Открыть виджет") { widgetOn = true; openWindow(id: "widget") }
                }
                Section("Обновление приложения") {
                    Text(updater.statusText).font(.caption)
                        .foregroundStyle({ if case .failed = updater.state { return Color.red }; return Color.secondary }())
                    Toggle("Обновлять автоматически", isOn: $updater.auto)
                    HStack {
                        Button("Проверить") { Task { await updater.check(model.serverBase) } }
                        if case .available(let info) = updater.state {
                            Button("Установить сборку \(info.build)") { Task { await updater.install(info) } }
                        }
                    }
                    Text("Новые версии берутся с сервера дома: проверка при запуске и раз в 6 часов, приложение перезапустится само.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Section("Система") {
                    Toggle("Запускать при входе в систему", isOn: Binding(get: { login }, set: { on in
                        do {
                            if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
                            login = on
                        } catch { login = (SMAppService.mainApp.status == .enabled) }
                    }))
                }
            }
        }
        .formStyle(.grouped)
    }

    private func label(_ p: Person) -> String {
        (p.emoji ?? "").isEmpty ? p.name : "\(p.emoji!) \(p.name)"
    }

    private func binding(for id: String, in keyPath: ReferenceWritableKeyPath<AppModel, Set<String>>) -> Binding<Bool> {
        Binding(
            get: { model[keyPath: keyPath].contains(id) },
            set: { on in
                if on { model[keyPath: keyPath].insert(id) } else { model[keyPath: keyPath].remove(id) }
            })
    }
}
