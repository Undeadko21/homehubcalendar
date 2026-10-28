import SwiftUI
import AppKit
import UserNotifications

final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        if Notifier.available {
            UNUserNotificationCenter.current().delegate = self
            if UserDefaults.standard.object(forKey: "notify") as? Bool ?? true { Notifier.requestAuthorization() }
        }
    }

    // Приложение живёт в строке меню и после закрытия окна.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { true }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
}

@main
struct HomeHubMacApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        Window("Домашний календарь", id: "main") {
            MainView(model: model)
        }
        Window("Настройки", id: "settings") {
            SettingsView(model: model).frame(width: 520)
        }
        .windowResizability(.contentSize)

        MenuBarExtra {
            MenuView(model: model)
        } label: {
            MenuLabel(model: model)
        }
        .menuBarExtraStyle(.window)
    }
}
