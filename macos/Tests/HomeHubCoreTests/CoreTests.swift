import XCTest
@testable import HomeHubCore

final class CoreTests: XCTestCase {
    // Сгенерировано сервером (backend/app/cloud.py encrypt): ключ 0..31
    let blob = "It3BPRnN33FPPL5bRqRSuPbfDQEqYZNWsgFjGG95WuL+WJedFhm6nrH2PPaSeYIVAP0gZumsddZQ6mCdu/zCtDEq+pNFby2MzksaiGYK8a+ciNEzgmf194a8eR4gy0lo26S9T39G2uA5XT39xbznDUZi8UvM4w2rlcLNa2s5Efvg3zB4JcGiUoSemwHxyU8="
    let key = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"

    func testDecryptsServerBlob() throws {
        let plain = try Cloud.decrypt(key: Cloud.base64url(key)!, blob: Data(base64Encoded: blob)!)
        let snap = try Snapshot.decode(plain)
        XCTAssertEqual(snap.people.first?.name, "Оля")
        XCTAssertEqual(snap.generated, "2026-10-28T13:00:00+05:00")
    }

    func testWrongKeyFails() {
        XCTAssertThrowsError(try Cloud.decrypt(key: Data(repeating: 1, count: 32), blob: Data(base64Encoded: blob)!))
    }

    func testRoundtripAndCode() throws {
        let k = Data(repeating: 7, count: 32)
        let enc = try Cloud.encrypt(key: k, plain: Data("привет".utf8))
        XCTAssertEqual(String(data: try Cloud.decrypt(key: k, blob: enc), encoding: .utf8), "привет")

        let json = #"{"u":"https://yadi.sk/d/abc","k":"AAEC","t":"y0_tok"}"#
        let code = "hhc1." + Data(json.utf8).base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
        let parsed = Cloud.parse(code)
        XCTAssertEqual(parsed?.url, "https://yadi.sk/d/abc")
        XCTAssertEqual(parsed?.token, "y0_tok")
        XCTAssertNil(Cloud.parse("мусор"))
    }

    func testAgendaPicksNextTimedEventOfSelectedPeople() throws {
        let tz = TimeZone(identifier: "Asia/Yekaterinburg")!
        let now = DateParse.parse("2026-10-28T13:00:00+05:00")!
        let events = [
            Event(id: "1", title: "Прошло", start: "2026-10-28T09:00:00+05:00", end: "2026-10-28T10:00:00+05:00", people: ["olya"]),
            Event(id: "2", title: "Весь день", start: "2026-10-28", end: "2026-10-29", allDay: true, people: ["olya"]),
            Event(id: "3", title: "Йога", start: "2026-10-28T19:00:00+05:00", end: "2026-10-28T20:00:00+05:00", people: ["olya"]),
            Event(id: "4", title: "Школа", start: "2026-10-28T15:00:00+05:00", end: "2026-10-28T16:00:00+05:00", people: ["masha"]),
        ]
        let all = Agenda.upcoming(events, people: [], now: now, timeZone: tz)
        XCTAssertEqual(all.map { $0.event.id }, ["4", "3"])
        let olya = Agenda.upcoming(events, people: ["olya"], now: now, timeZone: tz)
        XCTAssertEqual(olya.map { $0.event.id }, ["3"])
        var cal = Calendar(identifier: .gregorian); cal.timeZone = tz
        XCTAssertEqual(Agenda.menuTitle(olya.first, now: now, calendar: cal), "Йога · 19:00")
    }

    func testSnapshotTolerantToOldFormat() throws {
        let s = try Snapshot.decode(Data(#"{"v":1,"widget":{}}"#.utf8))
        XCTAssertTrue(s.events.isEmpty)
    }
}
