import SwiftUI
import UIKit
import BackgroundTasks
import UserNotifications

let refreshTaskID = "ru.homehub.calendar.refresh"

final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        if UserDefaults.standard.object(forKey: "notify") as? Bool ?? true { Notifier.requestAuthorization() }
        return true
    }

    // Уведомления показываем и когда приложение открыто.
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
}

func scheduleBackgroundRefresh() {
    let req = BGAppRefreshTaskRequest(identifier: refreshTaskID)
    req.earliestBeginDate = Date(timeIntervalSinceNow: 30 * 60)
    try? BGTaskScheduler.shared.submit(req)
}

@main
struct HomeHubApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model = AppModel()
    @Environment(\.scenePhase) private var phase

    var body: some Scene {
        WindowGroup {
            RootView(model: model)
        }
        .onChange(of: phase) { newPhase in
            if newPhase == .active {
                Task { await model.refresh() }
            } else if newPhase == .background {
                scheduleBackgroundRefresh()
            }
        }
        // iOS сам решает, когда запускать фоновое обновление: обычно раз в несколько часов.
        .backgroundTask(.appRefresh(refreshTaskID)) {
            scheduleBackgroundRefresh()
            await model.refresh()
        }
    }
}
