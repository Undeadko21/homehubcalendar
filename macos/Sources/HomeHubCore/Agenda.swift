import Foundation

/// Что показывать «дальше»: ближайшие события выбранных людей.
public struct AgendaItem: Identifiable, Hashable {
    public let event: Event
    public let start: Date
    public let end: Date
    public var id: String { event.id }
}

public enum Agenda {
    /// События со временем, которые ещё не закончились, по возрастанию начала. Пустой `people` — все.
    public static func upcoming(_ events: [Event], people: Set<String>, now: Date, timeZone: TimeZone = .current) -> [AgendaItem] {
        events.compactMap { e -> AgendaItem? in
            guard !e.allDay, people.isEmpty || !people.isDisjoint(with: e.people),
                  let s = DateParse.parse(e.start, timeZone: timeZone), let en = DateParse.parse(e.end, timeZone: timeZone),
                  max(s, en) >= now else { return nil }
            return AgendaItem(event: e, start: s, end: max(s, en))
        }.sorted { $0.start < $1.start }
    }

    static func formatter(_ fmt: String, _ timeZone: TimeZone) -> DateFormatter {
        let f = DateFormatter()
        f.locale = Locale(identifier: "ru_RU")
        f.timeZone = timeZone
        f.dateFormat = fmt
        return f
    }

    /// «Сегодня 19:00», «Завтра 08:00», «пн 08:00».
    public static func when(_ date: Date, now: Date, calendar: Calendar = .current) -> String {
        let time = formatter("HH:mm", calendar.timeZone).string(from: date)
        if calendar.isDate(date, inSameDayAs: now) { return time }
        if let tomorrow = calendar.date(byAdding: .day, value: 1, to: now), calendar.isDate(date, inSameDayAs: tomorrow) {
            return "завтра \(time)"
        }
        return "\(formatter("EE", calendar.timeZone).string(from: date)) \(time)"
    }

    /// Текст в строке меню: «Йога · 19:00» или «Сейчас: Йога».
    public static func menuTitle(_ item: AgendaItem?, now: Date, maxTitle: Int = 24, calendar: Calendar = .current) -> String {
        guard let item = item else { return "" }
        var title = item.event.title
        if title.count > maxTitle { title = String(title.prefix(maxTitle - 1)) + "…" }
        if item.start <= now { return "Сейчас: \(title)" }
        return "\(title) · \(when(item.start, now: now, calendar: calendar))"
    }
}
