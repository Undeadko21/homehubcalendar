import Foundation

/// Снимок календаря: тот же JSON, что отдаёт сервер (`/api/snapshot`) и что лежит зашифрованным на Яндекс.Диске.
public struct Person: Codable, Hashable, Identifiable {
    public let id: String
    public let name: String
    public let color: String?
    public let emoji: String?
}

public struct Duty: Codable, Hashable {
    public let role: String
}

public struct Event: Codable, Hashable, Identifiable {
    public let id: String
    public let title: String
    public let start: String
    public let end: String
    public let allDay: Bool
    public let location: String?
    public let people: [String]
    public let duty: Duty?

    enum CodingKeys: String, CodingKey {
        case id, title, start, end, allDay = "all_day", location, people, duty
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        start = try c.decode(String.self, forKey: .start)
        end = try c.decodeIfPresent(String.self, forKey: .end) ?? start
        allDay = try c.decodeIfPresent(Bool.self, forKey: .allDay) ?? false
        location = try c.decodeIfPresent(String.self, forKey: .location)
        people = try c.decodeIfPresent([String].self, forKey: .people) ?? []
        duty = try c.decodeIfPresent(Duty.self, forKey: .duty)
    }

    public init(id: String, title: String, start: String, end: String, allDay: Bool = false,
                location: String? = nil, people: [String] = [], duty: Duty? = nil) {
        self.id = id; self.title = title; self.start = start; self.end = end
        self.allDay = allDay; self.location = location; self.people = people; self.duty = duty
    }
}

public struct Reminder: Codable, Hashable, Identifiable {
    public let id: String
    public let kind: String
    public let at: String?
    public let start: String?
    public let people: [String]?
    public let title: String
    public let text: String?
}

public struct Snapshot: Codable {
    public let generated: String
    public let people: [Person]
    public let events: [Event]
    public let reminders: [Reminder]

    enum CodingKeys: String, CodingKey { case generated, people, events, reminders }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        generated = try c.decodeIfPresent(String.self, forKey: .generated) ?? ""
        people = try c.decodeIfPresent([Person].self, forKey: .people) ?? []
        events = try c.decodeIfPresent([Event].self, forKey: .events) ?? []
        reminders = try c.decodeIfPresent([Reminder].self, forKey: .reminders) ?? []
    }

    public init(generated: String = "", people: [Person] = [], events: [Event] = [], reminders: [Reminder] = []) {
        self.generated = generated; self.people = people; self.events = events; self.reminders = reminders
    }

    public static func decode(_ data: Data) throws -> Snapshot {
        try JSONDecoder().decode(Snapshot.self, from: data)
    }
}

public enum DateParse {
    /// Время из снимка: «2026-10-28T19:00:00+05:00», без пояса или просто дата (событие на весь день).
    public static func parse(_ s: String, timeZone: TimeZone = .current) -> Date? {
        let a = ISO8601DateFormatter()
        a.formatOptions = [.withInternetDateTime]
        if let d = a.date(from: s) { return d }
        let b = ISO8601DateFormatter()
        b.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = b.date(from: s) { return d }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = timeZone
        for fmt in ["yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm", "yyyy-MM-dd"] {
            f.dateFormat = fmt
            if let d = f.date(from: s) { return d }
        }
        return nil
    }
}
