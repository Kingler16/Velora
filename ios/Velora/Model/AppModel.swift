import Foundation
import Network
import Observation
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

    @ObservationIgnored let client: VeloraClient
    @ObservationIgnored private let monitor = NWPathMonitor()
    @ObservationIgnored private var seenFirstPath = false

    private static let endpointsKey = "serverEndpoints"

    init() {
        let stored = UserDefaults.standard.data(forKey: Self.endpointsKey)
            .flatMap { try? JSONDecoder().decode(ServerEndpoints.self, from: $0) }
        let endpoints = stored ?? .standard
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
    }

    /// Wechsel zwischen WLAN und Mobilfunk: Route neu bestimmen, damit nicht die Heim-IP ins Leere läuft.
    private func watchNetwork() {
        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in
                guard let self else { return }
                await self.client.invalidateRoute()
                self.route = nil
                // Der erste Aufruf kommt sofort beim Start – da laden die Ansichten ohnehin.
                if self.seenFirstPath, path.status == .satisfied { self.reloadToken += 1 }
                self.seenFirstPath = true
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
        return value
    }

    /// Zuletzt geladene Antwort, falls der Server gerade nicht erreichbar ist.
    func cached<T: Decodable>(_ path: String, as type: T.Type = T.self) -> (value: T, date: Date)? {
        guard let entry = ResponseCache.load(path), let value: T = try? VeloraClient.decode(entry.data) else { return nil }
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

enum AppTab: Hashable {
    case dashboard, portfolio, market, advisor, chat
}

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
