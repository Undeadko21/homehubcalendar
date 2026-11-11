import XCTest
import SwiftUI
import AppKit
import HomeHubCore
@testable import HomeHubMac

/// Рисует виджет рабочего стола в PNG (светлая и тёмная тема, три размера), чтобы смотреть вид без Mac.
/// Папка — $WIDGET_SNAP_DIR (в CI её забирает artifact), иначе временная.
@MainActor
final class WidgetSnapshotTests: XCTestCase {
    private func iso(_ d: Date) -> String {
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime]; return f.string(from: d)
    }

    private func model() -> AppModel {
        let cal = Calendar.current
        let now = cal.date(bySettingHour: 12, minute: 40, second: 0, of: Date())!
        func at(_ day: Int, _ h: Int, _ m: Int = 0) -> Date {
            cal.date(bySettingHour: h, minute: m, second: 0, of: cal.date(byAdding: .day, value: day, to: now)!)!
        }
        let people = [Person(id: "olya", name: "Оля", color: "#ff2d55", emoji: nil),
                      Person(id: "masha", name: "Маша", color: "#34c759", emoji: nil),
                      Person(id: "papa", name: "Папа", color: "#007aff", emoji: nil)]
        let events = [
            Event(id: "1", title: "Созвон с командой", start: iso(at(0, 12)), end: iso(at(0, 13, 30)), people: ["papa"]),
            Event(id: "2", title: "Танцы", start: iso(at(0, 16)), end: iso(at(0, 17, 30)), location: "ДК Урал", people: ["masha"]),
            Event(id: "3", title: "Йога", start: iso(at(0, 19)), end: iso(at(0, 20)), people: ["olya"]),
            Event(id: "4", title: "Школа", start: iso(at(1, 8)), end: iso(at(1, 13, 30)), people: ["masha"]),
            Event(id: "5", title: "Родительское собрание", start: iso(at(1, 18)), end: iso(at(1, 19)), people: ["olya", "papa"], color: "#ff9500"),
            Event(id: "6", title: "День рождения бабушки", start: iso(at(1, 0)), end: iso(at(2, 0)), allDay: true, people: ["olya"]),
        ]
        let m = AppModel()
        m.loadPreview(Snapshot(generated: iso(now), people: people, events: events), now: now)
        return m
    }

    func testRenderWidgets() throws {
        let dir = URL(fileURLWithPath: ProcessInfo.processInfo.environment["WIDGET_SNAP_DIR"] ?? NSTemporaryDirectory())
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let m = model()
        var written = 0
        for size in WidgetSize.allCases {
            for dark in [false, true] {
                let view = DesktopWidgetView(model: m)
                    .frame(width: size.size.width, height: size.size.height)
                    .background(dark ? Color(white: 0.12) : Color(white: 0.92))
                    .environment(\.colorScheme, dark ? .dark : .light)
                let r = ImageRenderer(content: view)
                r.scale = 2
                guard let img = r.nsImage, let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
                      let png = rep.representation(using: .png, properties: [:]) else {
                    XCTFail("не удалось отрисовать \(size.rawValue)"); continue
                }
                try png.write(to: dir.appendingPathComponent("widget-\(size.rawValue)-\(dark ? "dark" : "light").png"))
                written += 1
            }
        }
        XCTAssertEqual(written, WidgetSize.allCases.count * 2)
    }
}
