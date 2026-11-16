import Foundation
import UserNotifications

/// Срок подписи приложения. С бесплатным Apple ID (AltStore, Sideloadly) подпись живёт 7 дней,
/// после чего iPhone перестаёт открывать приложение. Срок записан в профиле внутри самого приложения.
enum Signing {
    private static let reminderID = "hh.signing"

    static let expires: Date? = {
        guard let url = Bundle.main.url(forResource: "embedded", withExtension: "mobileprovision"),
              let data = try? Data(contentsOf: url),
              let from = data.range(of: Data("<?xml".utf8)),
              let to = data.range(of: Data("</plist>".utf8), options: [], in: from.lowerBound..<data.endIndex)
        else { return nil }
        let xml = data.subdata(in: from.lowerBound..<to.upperBound)
        guard let any = try? PropertyListSerialization.propertyList(from: xml, options: [], format: nil),
              let plist = any as? [String: Any]
        else { return nil }
        return plist["ExpirationDate"] as? Date
    }()

    /// Строка для настроек: «Подпись действует до 23 ноября, 15:02».
    static func text(now: Date = Date()) -> String? {
        guard let end = expires else { return nil }
        let f = DateFormatter()
        f.locale = Locale(identifier: "ru_RU")
        f.dateFormat = "d MMMM, HH:mm"
        let left = end.timeIntervalSince(now)
        if left <= 0 { return "Подпись истекла \(f.string(from: end))" }
        return "Подпись действует до \(f.string(from: end))" + (left < 2 * 86400 ? " — пора продлить" : "")
    }

    /// Напоминание за сутки до конца подписи. Если осталось меньше суток — один раз, через минуту.
    static func scheduleReminder(now: Date = Date()) {
        guard let end = expires, end > now else { return }
        let center = UNUserNotificationCenter.current()
        var delay = end.addingTimeInterval(-24 * 3600).timeIntervalSince(now)
        if delay < 60 {
            let stamp = end.timeIntervalSince1970
            if UserDefaults.standard.double(forKey: "hh.signingWarned") == stamp { return }
            UserDefaults.standard.set(stamp, forKey: "hh.signingWarned")
            delay = 60
        }
        let content = UNMutableNotificationContent()
        content.title = "Продлите подпись календаря"
        content.body = "Завтра приложение перестанет открываться. Обновите его через AltStore (Refresh All) или Sideloadly рядом с компьютером."
        content.sound = .default
        center.removePendingNotificationRequests(withIdentifiers: [reminderID])
        center.add(UNNotificationRequest(identifier: reminderID, content: content,
                                         trigger: UNTimeIntervalNotificationTrigger(timeInterval: delay, repeats: false)))
    }
}
