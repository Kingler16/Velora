import Synchronization
import UIKit
import UserNotifications
import VeloraKit

/// Welcher Chat gerade offen ist. Der Mitteilungs-Delegate fragt das außerhalb des
/// MainActors ab, um eine Antwort nicht doppelt zu melden, die man ohnehin sieht.
nonisolated let openChatThread = Mutex<String?>(nil)

/// Hält das AppModel und nimmt von iOS Gerätetoken und Mitteilungen entgegen.
/// Das Modell lebt hier statt in der App-Struktur, damit ein Tipp auf eine
/// Mitteilung auch beim Kaltstart schon ein Ziel hat.
final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    let model = AppModel()

    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        model.pushTokenReceived(deviceToken.map { String(format: "%02x", $0) }.joined())
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        model.pushRegistrationFailed(error.localizedDescription)
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
                                            willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        let info = PushInfo(userInfo: notification.request.content.userInfo)
        let visible = info.chatThreadID != nil && openChatThread.withLock { $0 } == info.chatThreadID
        completionHandler(visible ? [] : [.banner, .list, .sound])
        Task { @MainActor in self.model.reloadAll() }
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
                                            didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping () -> Void) {
        let info = PushInfo(userInfo: response.notification.request.content.userInfo)
        Task { @MainActor in self.model.open(info.target) }
        completionHandler()
    }
}

enum PushEnvironment {
    /// Xcode-Builds tragen ein Entwicklungsprofil mit `aps-environment = development`
    /// und bekommen Tokens vom Sandbox-Server. TestFlight und App Store haben kein
    /// eingebettetes Profil → Produktion.
    static let current: String = {
        guard let url = Bundle.main.url(forResource: "embedded", withExtension: "mobileprovision"),
              let data = try? Data(contentsOf: url),
              let text = String(data: data, encoding: .isoLatin1),
              let key = text.range(of: "<key>aps-environment</key>") else { return "production" }
        return text[key.upperBound...].prefix(80).contains("development") ? "sandbox" : "production"
    }()
}
