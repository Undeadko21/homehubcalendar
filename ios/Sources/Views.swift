import SwiftUI
import UIKit
#if canImport(HomeHubCore)
import HomeHubCore
#endif

struct RootView: View {
    @ObservedObject var model: AppModel
    @State private var sheet: Sheet?

    enum Sheet: String, Identifiable {
        case next, settings
        var id: String { rawValue }
    }

    var body: some View {
        NavigationStack {
            content
                .navigationTitle(model.menuTitle.isEmpty ? "Календарь" : model.menuTitle)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .navigationBarLeading) {
                        Button { sheet = .next } label: { Image(systemName: "list.bullet") }
                            .accessibilityLabel("Ближайшие события")
                    }
                    ToolbarItem(placement: .navigationBarTrailing) {
                        Button { sheet = .settings } label: { Image(systemName: "gearshape") }
                            .accessibilityLabel("Подключение")
                    }
                }
        }
        .sheet(item: $sheet) { which in
            switch which {
            case .next: NextSheet(model: model)
            case .settings: SettingsSheet(model: model)
            }
        }
        .onAppear { if !model.configured { sheet = .settings } }
    }

    @ViewBuilder private var content: some View {
        if model.webOK, let url = model.serverBase {
            WebView(url: url, reloadToken: model.reloadToken)
        } else if model.configured {
            OfflineList(model: model)
        } else {
            VStack(spacing: 12) {
                Image(systemName: "calendar").font(.system(size: 44)).foregroundStyle(.red)
                Text("Подключите календарь").font(.title3.weight(.semibold))
                Button("Открыть настройки") { sheet = .settings }.buttonStyle(.borderedProminent)
            }
        }
    }
}

// MARK: - Список событий (когда сервер недоступен и в листе «Ближайшие»)

struct ItemRow: View {
    let item: AgendaItem
    @ObservedObject var model: AppModel

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(item.start <= model.now ? "сейчас" : Agenda.when(item.start, now: model.now))
                .font(.system(.callout, design: .rounded).weight(.semibold))
                .foregroundStyle(item.start <= model.now ? Color.red : Color.primary)
                .frame(width: 84, alignment: .leading)
            VStack(alignment: .leading, spacing: 1) {
                Text(item.event.title).lineLimit(2)
                let who = names
                if !who.isEmpty { Text(who).font(.caption).foregroundStyle(.secondary) }
            }
        }
    }

    private var names: String {
        item.event.people.compactMap { id in model.people.first { $0.id == id } }
            .map { ($0.emoji ?? "").isEmpty ? $0.name : "\($0.emoji!) \($0.name)" }
            .joined(separator: ", ")
    }
}

struct OfflineList: View {
    @ObservedObject var model: AppModel

    private var days: [(Date, [AgendaItem])] {
        let cal = Calendar.current
        let end = cal.date(byAdding: .day, value: 8, to: cal.startOfDay(for: model.now)) ?? model.now
        let items = model.upcoming.filter { $0.start < end }
        let grouped = Dictionary(grouping: items) { cal.startOfDay(for: $0.start) }
        return grouped.keys.sorted().map { ($0, grouped[$0] ?? []) }
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

    var body: some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.statusText).font(.callout.weight(.semibold))
                    if let e = model.error { Text(e).font(.caption).foregroundStyle(.secondary) }
                }
            }
            if days.isEmpty {
                Text("Ближайших событий нет").foregroundStyle(.secondary)
            }
            ForEach(days, id: \.0) { day, items in
                Section(header: Text(Self.dayName(day, now: model.now))) {
                    ForEach(items) { ItemRow(item: $0, model: model) }
                }
            }
        }
        .refreshable { await model.refresh() }
    }
}

struct NextSheet: View {
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            OfflineList(model: model)
                .navigationTitle("Ближайшие")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Готово") { dismiss() } } }
        }
    }
}

// MARK: - Подключение и настройки

struct SettingsSheet: View {
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section(header: Text("Подключение"), footer: Text("Дома приложение ходит на сервер, вне дома читает снимок из облака. Код подключения — в настройках календаря → Подключение → Облако.")) {
                    TextField("Сервер дома, например http://192.168.0.10:8080", text: $model.serverURL)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    TextField("Код подключения (вне дома)", text: $model.code, axis: .vertical)
                        .lineLimit(1...3).textInputAutocapitalization(.never).autocorrectionDisabled()
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
                if !model.people.isEmpty {
                    Section(header: Text("Чьи события в заголовке")) {
                        ForEach(model.people) { p in
                            Toggle(label(p), isOn: binding(for: p.id, in: \.menuPeople))
                        }
                    }
                }
                Section(header: Text("Уведомления"), footer: Text("iOS сама решает, когда обновлять данные в фоне, поэтому напоминания надёжнее, если иногда открывать приложение.")) {
                    Toggle("Показывать уведомления", isOn: $model.notify)
                    if model.notify {
                        Stepper("Поездки: за \(model.lead) мин", value: $model.lead, in: 5...120, step: 5)
                        ForEach(model.people) { p in
                            Toggle("Напоминать: \(label(p))", isOn: binding(for: p.id, in: \.tripPeople))
                        }
                    }
                }
            }
            .navigationTitle("Настройки")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Готово") { dismiss() } } }
        }
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
