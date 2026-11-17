import XCTest
@testable import HomeHubCore

/// Снимок в `Fixtures/snapshot.json` — настоящий вывод сервера (`backend/tests/test_swift_fixture.py` сверяет его форму с кодом сервера
/// и умеет перезаписать файл). Здесь проверяем, что Mac/iPhone читают именно то, что сервер отдаёт сегодня.
final class SnapshotFixtureTests: XCTestCase {
    func load() throws -> Snapshot {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("Fixtures/snapshot.json")
        return try Snapshot.decode(try Data(contentsOf: url))
    }

    func testServerSnapshotDecodes() throws {
        let s = try load()
        XCTAssertEqual(s.generated, "2026-11-03T09:00:00+05:00")
        XCTAssertEqual(s.people.map { $0.id }.sorted(), ["anna", "mark"])
        XCTAssertEqual(s.events.count, 4)
        XCTAssertEqual(s.reminders.count, 4)
    }

    func testEventsKeepColorAllDayAndDuty() throws {
        let s = try load()
        let swim = try XCTUnwrap(s.events.first { $0.title == "Плавание" })
        XCTAssertEqual(swim.color, "#ff9500")
        XCTAssertEqual(swim.location, "Бассейн Юность")
        XCTAssertEqual(swim.people, ["mark"])
        let day = try XCTUnwrap(s.events.first { $0.title == "День района" })
        XCTAssertTrue(day.allDay)
        let duty = try XCTUnwrap(s.events.first { $0.duty != nil })
        XCTAssertEqual(duty.duty?.role, "pickup")
        XCTAssertEqual(duty.people, ["anna"])
    }

    func testTripAlertCarriesActionButtonData() throws {
        let s = try load()
        let alert = try XCTUnwrap(s.reminders.first { $0.kind == "alert" })
        XCTAssertTrue(alert.id.hasPrefix("alert:trip:"))
        let trip = try XCTUnwrap(alert.trip)
        XCTAssertEqual(trip.need.map { $0.role }, ["dropoff"])
        XCTAssertNil(trip.need[0].person)
        XCTAssertEqual(trip.need[0].free, ["anna"])
        XCTAssertEqual(trip.names?["anna"], "Анна")
        XCTAssertNotNil(trip.uid)
        XCTAssertNil(trip.occurrence)          // одиночное событие — без даты повтора
        XCTAssertNotNil(DateParse.parse(try XCTUnwrap(alert.at)))
        XCTAssertNotNil(DateParse.parse(try XCTUnwrap(alert.start)))
    }

    func testReminderTimesParseAndOrder() throws {
        let s = try load()
        for r in s.reminders {
            if let at = r.at { XCTAssertNotNil(DateParse.parse(at), "не разобралось время напоминания \(r.id)") }
        }
        let bdays = s.reminders.filter { $0.kind == "bday" }
        XCTAssertEqual(bdays.count, 2)
        XCTAssertTrue(bdays.allSatisfy { $0.title.contains("день рождения") })
        let duty = try XCTUnwrap(s.reminders.first { $0.kind == "duty" })
        XCTAssertEqual(duty.people ?? [], ["anna"])
        XCTAssertNil(duty.at)                  // без «at» — приложение считает время само от start и настроек
    }

    func testAgendaFromServerSnapshot() throws {
        let s = try load()
        let tz = TimeZone(identifier: "Asia/Yekaterinburg")!
        let now = try XCTUnwrap(DateParse.parse(s.generated))
        let all = Agenda.upcoming(s.events, people: [], now: now, timeZone: tz)
        // со временем и не закончились: Плавание 17:00, поездка «Забрать» 18:00–18:30 (виден как событие), Йога 19:30; «весь день» не берём
        XCTAssertEqual(all.map { $0.event.title }, ["Плавание", "Забрать Марка: Плавание", "Йога"])
        XCTAssertEqual(Agenda.upcoming(s.events, people: ["mark"], now: now, timeZone: tz).map { $0.event.title }, ["Плавание"])
    }

    func testUnknownFieldsAndMissingOnesAreTolerated() throws {
        // новый сервер добавил поле, старый снимок без части полей — оба должны читаться
        let json = #"{"v":9,"generated":"2026-11-03T09:00:00+05:00","brand_new":{"x":1},"people":[{"id":"a","name":"А","extra":true}],"events":[{"id":"e","title":"T","start":"2026-11-03","future":1}],"reminders":[{"id":"r","kind":"alert","title":"Т","what":"?"}]}"#
        let s = try Snapshot.decode(Data(json.utf8))
        XCTAssertEqual(s.events.first?.end, "2026-11-03")
        XCTAssertEqual(s.events.first?.allDay, false)
        XCTAssertNil(s.reminders.first?.trip)
    }
}
