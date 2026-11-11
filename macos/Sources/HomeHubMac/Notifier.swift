import Foundation
import UserNotifications
#if canImport(HomeHubCore)
import HomeHubCore
#endif

/// Локальные уведомления из блока `reminders` снимка: поездки за N минут, вечерний дайджест, дни рождения.
/// Каждый раз пересоздаём очередь целиком, поэтому изменения на сервере подхватываются сами.
enum Notifier {
    static var available: Bool { Bundle.main.bundleIdentifier != nil }

    static func requestAuthorization() {
        guard available else { return }
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    static func schedule(_ snap: Snapshot, enabled: Bool, tripPeople: Set<String>, lead: Int) {
        guard available else { return }
        let center = UNUserNotificationCenter.current()
        let reminders = snap.reminders
        center.getPendingNotificationRequests { pending in
            let ours = pending.map { $0.identifier }.filter { $0.hasPrefix("hh:") }
            center.removePendingNotificationRequests(withIdentifiers: ours)
            guard enabled else { return }
            let now = Date()
            var items: [(Date, Reminder)] = []
            let defaults = UserDefaults.standard
            var shown = Set(defaults.stringArray(forKey: "hh.shownAlerts") ?? [])
            var fresh: [String] = []
            for r in reminders {
                var fire: Date?
                if r.kind == "duty" {
                    // «За сколько минут» и «чьи поездки» решает само приложение (у каждого устройства свои).
                    guard !tripPeople.isDisjoint(with: r.people ?? []),
                          let s = r.start.flatMap({ DateParse.parse($0) }) else { continue }
                    fire = s.addingTimeInterval(-Double(lead) * 60)
                } else if let at = r.at {
                    // Напоминания о встречах: время считает сервер по настройкам человека, здесь только «чьи».
                    if r.kind == "event", tripPeople.isDisjoint(with: r.people ?? []) { continue }
                    fire = DateParse.parse(at)
                }
                if let f = fire, f > now { items.append((f, r)) }
                else if let f = fire, ["alert", "digest"].contains(r.kind), now.timeIntervalSince(f) < 24 * 3600,
                        !shown.contains(r.id) {
                    // Срочные предупреждения (поездка без водителя, дайджест, молчащая синхронизация) приходят, когда уже
                    // «пора»: показываем сразу, один раз на устройство.
                    items.append((now.addingTimeInterval(2), r)); fresh.append(r.id)
                }
            }
            if !fresh.isEmpty {
                shown.formUnion(fresh)
                defaults.set(Array(shown.suffix(200)), forKey: "hh.shownAlerts")
            }
            items.sort { $0.0 < $1.0 }
            var categories: Set<UNNotificationCategory> = []
            for (fire, r) in items.prefix(60) {
                let content = UNMutableNotificationContent()
                content.title = r.title
                content.body = r.text ?? ""
                content.sound = .default
                if let (cat, ops) = tripCategory(r, tripPeople: tripPeople) {
                    categories.insert(cat)
                    content.categoryIdentifier = cat.identifier
                    content.userInfo = ["ops": ops]
                }
                let trigger = UNTimeIntervalNotificationTrigger(timeInterval: max(1, fire.timeIntervalSinceNow), repeats: false)
                center.add(UNNotificationRequest(identifier: "hh:" + r.id, content: content, trigger: trigger))
            }
            center.setNotificationCategories(categories)
        }
    }

    /// Код подключения этого устройства (его хранит AppModel); для кнопок нужен токен записи `t`.
    static var code: ConnectionCode? {
        UserDefaults.standard.string(forKey: "cloudCode").flatMap { Cloud.parse($0) }
    }

    /// Кнопки «Отвезу я / Заберу я / Не могу» для срочного напоминания о поездке (как на Android).
    /// «Я» — если на устройстве выбран один человек для напоминаний; иначе кнопки по имени свободных взрослых.
    /// Команда кладётся в облако одноразовым файлом, сервер применит её за минуту. Без токена записи кнопок нет.
    static func tripCategory(_ r: Reminder, tripPeople: Set<String>) -> (UNNotificationCategory, [String: [String: String]])? {
        guard r.kind == "alert", let trip = r.trip, let uid = trip.uid, code?.token != nil else { return nil }
        let me = tripPeople.count == 1 ? tripPeople.first : nil
        var actions: [UNNotificationAction] = []
        var ops: [String: [String: String]] = [:]
        var cantRole: String?
        func op(_ role: String, _ person: String?) -> [String: String] {
            var o = ["type": "escort", "uid": uid, "role": role]
            if let occ = trip.occurrence { o["occurrence"] = occ }
            if let p = person { o["person"] = p }
            return o
        }
        for n in trip.need where actions.count < 2 {
            let drop = n.role == "dropoff"
            if let me = me, n.person == me { cantRole = cantRole ?? n.role }
            var who: String?
            var label = ""
            if let me = me {
                if n.free.contains(me) && n.person != me { who = me; label = drop ? "Отвезу я" : "Заберу я" }
            } else if let p = n.free.first(where: { $0 != n.person }) {
                let name = trip.names?[p] ?? p
                who = p; label = drop ? "Отвезёт \(name)" : "Заберёт \(name)"
            }
            guard let person = who else { continue }
            let aid = "hh.a\(actions.count)"
            actions.append(UNNotificationAction(identifier: aid, title: label, options: []))
            ops[aid] = op(n.role, person)
        }
        if let role = cantRole {
            actions.append(UNNotificationAction(identifier: "hh.cant", title: "Не могу", options: [.destructive]))
            ops["hh.cant"] = op(role, nil)   // снять назначение: остальные увидят, что везти некому
        }
        guard !actions.isEmpty else { return nil }
        let cat = UNNotificationCategory(identifier: "hh.trip." + String(r.id.hashValue, radix: 36),
                                         actions: actions, intentIdentifiers: [], options: [])
        return (cat, ops)
    }

    /// Нажали кнопку в уведомлении: отправить команду и показать короткий итог.
    static func handle(_ response: UNNotificationResponse, done: @escaping () -> Void) {
        let info = response.notification.request.content.userInfo
        guard let ops = info["ops"] as? [String: [String: String]], let op = ops[response.actionIdentifier],
              let code = code else { done(); return }
        Task {
            var body = "Отправлено, календарь обновится в течение минуты"
            do { try await Cloud.sendOp(code, op: op) } catch { body = "Не удалось отправить: \(error.localizedDescription)" }
            let content = UNMutableNotificationContent()
            content.title = op["person"] == nil ? "Назначение снято" : "Готово"
            content.body = body
            try? await UNUserNotificationCenter.current().add(
                UNNotificationRequest(identifier: "hh-done-" + UUID().uuidString, content: content, trigger: nil))
            done()
        }
    }
}
