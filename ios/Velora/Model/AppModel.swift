import Foundation
import Network
import Observation
import UIKit
import UserNotifications
import VeloraKit

/// Zentraler Zustand: Server-Verbindung, Zwischenspeicher der letzten Antworten, Daten-Refresh.
@Observable
final class AppModel {
    private(set) var endpoints: ServerEndpoints
    private(set) var route: Route?
    /// Wechselt bei jeder Änderung, die alle Ansichten neu laden soll (Refresh fertig, neue Adresse, Netzwechsel).
    private(set) var reloadToken = 0
    private(set) var refreshRunning = false
    var selectedTab: AppTab = .dashboard
    /// Welcher Bereich im Berater-Tab offen ist – Empfehlungen zuerst, weil dort das Handeln liegt.
    var advisorSection: AdvisorSection = .recommendations
    /// Offene, umsetzbare Empfehlungen – Badge am Berater-Tab.
    private(set) var actionableCount = 0
    /// Letzter bekannter EUR/USD-Kurs (Dollar je Euro) für Euro-Gegenwerte.
    private(set) var eurUsd: Double?
    /// Chat, den ein Tipp auf eine Mitteilung öffnen soll – die Chat-Liste holt ihn ab.
    var pendingChatThreadID: String?
    /// Ob iOS Mitteilungen erlaubt; `nil` solange unbekannt.
    private(set) var notificationsAllowed: Bool?
    private(set) var pushError: String?

    @ObservationIgnored let client: VeloraClient
    @ObservationIgnored private let monitor = NWPathMonitor()
    @ObservationIgnored private var network: NetworkState?
    @ObservationIgnored private var deviceToken: String?

    private static let endpointsKey = "serverEndpoints"

    init() {
        let stored = UserDefaults.standard.data(forKey: Self.endpointsKey)
            .flatMap { try? JSONDecoder().decode(ServerEndpoints.self, from: $0) }
        let endpoints = stored ?? .initial(defaultServer: Bundle.main.object(forInfoDictionaryKey: "VeloraDefaultServer") as? String)
        self.endpoints = endpoints
        client = VeloraClient(endpoints: endpoints, password: Keychain.password)
        watchNetwork()
    }

    var password: String { Keychain.password }

    func updateServer(_ endpoints: ServerEndpoints, password: String) async {
        self.endpoints = endpoints
        Keychain.password = password
        UserDefaults.standard.set(try? JSONEncoder().encode(endpoints), forKey: Self.endpointsKey)
        await client.configure(endpoints: endpoints, password: password)
        route = nil
        reloadToken += 1
        await registerPushToken()
    }

    /// Wechsel zwischen WLAN und Mobilfunk: Route neu bestimmen, damit nicht die Heim-IP ins Leere läuft.
    /// Mit aktivem VPN meldet iOS viele Pfad-Updates ohne echte Änderung (Tailscale verbindet
    /// sich neu, Schnittstellen wechseln) – nur eine echte Änderung der Netzlage zählt.
    private func watchNetwork() {
        monitor.pathUpdateHandler = { [weak self] path in
            let online = path.status == .satisfied
            let wifi = path.availableInterfaces.contains { $0.type == .wifi }
            Task { @MainActor in
                guard let self else { return }
                let state = NetworkState(online: online, wifi: wifi)
                guard state != self.network else { return }
                let cameBack = self.network?.online == false && online
                self.network = state
                await self.client.setNetwork(wifiAvailable: wifi)
                self.route = await self.client.route
                // Nur neu laden, wenn das Netz weg war – sonst bricht jedes Update laufende Anfragen ab.
                if cameBack { self.reloadToken += 1 }
            }
        }
        monitor.start(queue: DispatchQueue(label: "velora.network"))
    }

    // MARK: - Laden

    /// Lädt eine Ansicht vom Server und legt die Antwort für den Offline-Fall ab.
    func load<T: Decodable>(_ path: String, as type: T.Type = T.self) async throws -> T {
        let data = try await client.getData(path)
        route = await client.route
        let value: T = try VeloraClient.decode(data)
        ResponseCache.store(data, for: path)
        if let counting = value as? ActionableCounting { actionableCount = counting.actionableTotal }
        if let fx = (value as? EurUsdProviding)?.eurUsdRate, fx > 0 { eurUsd = fx }
        return value
    }

    /// Zuletzt geladene Antwort, falls der Server gerade nicht erreichbar ist.
    func cached<T: Decodable>(_ path: String, as type: T.Type = T.self) -> (value: T, date: Date)? {
        guard let entry = ResponseCache.load(path), let value: T = try? VeloraClient.decode(entry.data) else { return nil }
        if actionableCount == 0, let counting = value as? ActionableCounting { actionableCount = counting.actionableTotal }
        if eurUsd == nil, let fx = (value as? EurUsdProviding)?.eurUsdRate, fx > 0 { eurUsd = fx }
        return (value, entry.date)
    }

    /// Schreibaktion ausführen; danach laden alle Ansichten neu.
    @discardableResult
    func send(_ path: String, _ body: [String: JSONValue] = [:], method: String = "POST") async throws -> ActionResult {
        let result = try await client.send(path, method: method, body: body)
        route = await client.route
        reloadToken += 1
        return result
    }

    func reloadAll() { reloadToken += 1 }

    // MARK: - Mitteilungen

    /// Fragt beim ersten Start nach der Erlaubnis und holt danach das Gerätetoken.
    /// Builds ohne Push-Berechtigung (kostenloser Apple-Account) fragen gar nicht erst.
    func setUpNotifications() async {
        guard PushEnvironment.current != nil else { return }
        let center = UNUserNotificationCenter.current()
        var settings = await center.notificationSettings()
        if settings.authorizationStatus == .notDetermined {
            _ = try? await center.requestAuthorization(options: [.alert, .sound, .badge])
            settings = await center.notificationSettings()
        }
        let allowed = [.authorized, .provisional, .ephemeral].contains(settings.authorizationStatus)
        notificationsAllowed = allowed
        if allowed { UIApplication.shared.registerForRemoteNotifications() }
    }

    func pushTokenReceived(_ token: String) {
        deviceToken = token
        pushError = nil
        Task { await registerPushToken() }
    }

    func pushRegistrationFailed(_ message: String) {
        pushError = message
    }

    /// Meldet das Gerät beim Server an. Bei jedem Start und Serverwechsel – Tokens können sich ändern,
    /// und ohne Verbindung klappt es eben beim nächsten Mal.
    func registerPushToken() async {
        guard let deviceToken, let environment = PushEnvironment.current else { return }
        let info = Bundle.main.infoDictionary
        let version = "\(info?["CFBundleShortVersionString"] as? String ?? "?") (\(info?["CFBundleVersion"] as? String ?? "?"))"
        do {
            try await client.send("/api/push/apns/register", body: [
                "token": .string(deviceToken),
                "environment": .string(environment),
                "device_name": .string(UIDevice.current.name),
                "app_version": .string(version),
            ])
            pushError = nil
        } catch {
            pushError = error.localizedDescription
        }
    }

    /// Tipp auf eine Mitteilung: passenden Tab bzw. Chat öffnen.
    func open(_ target: PushTarget) {
        switch target {
        case .dashboard: selectedTab = .dashboard
        case .portfolio: selectedTab = .portfolio
        case .briefings:
            advisorSection = .briefings
            selectedTab = .advisor
        case .recommendations:
            advisorSection = .recommendations
            selectedTab = .advisor
        case .chat(let id):
            pendingChatThreadID = id
            selectedTab = .chat
        }
        reloadToken += 1
    }

    // MARK: - Daten-Refresh am Server

    /// Startet am Pi den Abruf frischer Marktdaten und wartet, bis er fertig ist.
    func refreshServerData() async throws {
        try await client.send("/api/refresh")
        refreshRunning = true
        defer { refreshRunning = false }
        nonisolated struct Status: Decodable { var running: Bool }
        for _ in 0..<120 {
            try await Task.sleep(for: .seconds(2))
            let status: Status = try await client.get("/api/refresh/status")
            if !status.running { break }
        }
        reloadToken += 1
    }
}

private struct NetworkState: Equatable {
    var online: Bool
    var wifi: Bool
}

enum AppTab: Hashable {
    case dashboard, portfolio, market, advisor, chat
}

enum AdvisorSection: String, CaseIterable, Identifiable {
    case recommendations = "Empfehlungen", briefings = "Briefings"
    var id: Self { self }
}

/// Antworten, die die Zahl offener Empfehlungen kennen (fürs Tab-Badge).
protocol ActionableCounting { var actionableTotal: Int { get } }
extension DashboardData: ActionableCounting { var actionableTotal: Int { actionable.count } }
extension RecommendationsData: ActionableCounting { var actionableTotal: Int { actionableCount } }

/// Antworten mit EUR/USD-Kurs.
protocol EurUsdProviding { var eurUsdRate: Double? { get } }
extension DashboardData: EurUsdProviding { var eurUsdRate: Double? { eurUsd } }
extension PortfolioData: EurUsdProviding { var eurUsdRate: Double? { eurUsd } }
extension RecommendationsData: EurUsdProviding { var eurUsdRate: Double? { eurUsd } }

/// Letzte Server-Antworten je Pfad im Caches-Ordner – damit die App auch ohne Verbindung etwas zeigt.
enum ResponseCache {
    private static var directory: URL {
        let dir = URL.cachesDirectory.appending(path: "responses", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    private static func file(_ path: String) -> URL {
        directory.appending(path: path.replacingOccurrences(of: "/", with: "_") + ".json")
    }

    static func store(_ data: Data, for path: String) {
        try? data.write(to: file(path), options: [.atomic, .completeFileProtection])
    }

    static func load(_ path: String) -> (data: Data, date: Date)? {
        let url = file(path)
        guard let data = try? Data(contentsOf: url) else { return nil }
        let date = (try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
        return (data, date)
    }
}
