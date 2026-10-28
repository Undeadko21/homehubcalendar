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
            }
            items.sort { $0.0 < $1.0 }
            for (fire, r) in items.prefix(60) {
                let content = UNMutableNotificationContent()
                content.title = r.title
                content.body = r.text ?? ""
                content.sound = .default
                let trigger = UNTimeIntervalNotificationTrigger(timeInterval: max(1, fire.timeIntervalSinceNow), repeats: false)
                center.add(UNNotificationRequest(identifier: "hh:" + r.id, content: content, trigger: trigger))
            }
        }
    }
}
