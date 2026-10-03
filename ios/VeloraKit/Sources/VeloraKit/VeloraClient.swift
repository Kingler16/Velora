import Foundation

/// Erreichbare Adressen des Velora-Servers. Zu Hause direkt im WLAN, unterwegs über Tailscale.
public struct ServerEndpoints: Codable, Sendable, Equatable {
    public var lan: String
    public var remote: String

    public init(lan: String, remote: String) {
        self.lan = lan
        self.remote = remote
    }

    public static let standard = ServerEndpoints(lan: "http://192.168.1.27:8080", remote: "")

    /// Standard-Port des Velora-Webservers (`web.port` in settings.json).
    public static let defaultPort = 8080

    /// Normalisiert Eingaben wie `100.69.43.83` → `http://100.69.43.83:8080`.
    public static func url(from string: String) -> URL? {
        var s = string.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !s.isEmpty else { return nil }
        if !s.contains("://") { s = "http://" + s }
        while s.hasSuffix("/") { s.removeLast() }
        guard var components = URLComponents(string: s), components.host?.isEmpty == false else { return nil }
        // Ohne Port würde HTTP auf 80 landen – Velora lauscht aber auf 8080.
        if components.port == nil, components.scheme == "http" { components.port = defaultPort }
        return components.url
    }

    var candidates: [(Route, URL)] {
        [(Route.lan, lan), (Route.remote, remote)].compactMap { route, s in
            Self.url(from: s).map { (route, $0) }
        }
    }
}

public enum Route: String, Sendable {
    case lan = "WLAN"
    case remote = "Tailscale"
}

public enum VeloraError: LocalizedError, Sendable {
    case notConfigured
    case unreachable([String])
    case unauthorized
    case server(Int, String)
    case decoding(String)

    public var errorDescription: String? {
        switch self {
        case .notConfigured: "Keine Server-Adresse eingetragen."
        case .unreachable(let attempts):
            (["Velora ist nicht erreichbar. Im WLAN zu Hause oder mit aktivem Tailscale erneut versuchen."] + attempts)
                .joined(separator: "\n")
        case .unauthorized: "Der Server verlangt ein Passwort. Bitte in den Einstellungen eintragen."
        case .server(let code, let message): message.isEmpty ? "Serverfehler \(code)" : message
        case .decoding(let detail): "Unerwartete Antwort vom Server (\(detail))."
        }
    }
}

public actor VeloraClient {
    public private(set) var endpoints: ServerEndpoints
    private var password: String
    private var resolved: (route: Route, url: URL)?
    private let session: URLSession

    public init(endpoints: ServerEndpoints, password: String = "", session: URLSession? = nil) {
        self.endpoints = endpoints
        self.password = password
        self.session = session ?? {
            let config = URLSessionConfiguration.default
            config.waitsForConnectivity = false
            config.httpCookieStorage = nil  // Login läuft über den Header unten
            return URLSession(configuration: config)
        }()
    }

    public func configure(endpoints: ServerEndpoints, password: String) {
        self.endpoints = endpoints
        self.password = password
        resolved = nil
    }

    /// Nach einem Netzwechsel neu ermitteln, ob WLAN oder Tailscale.
    public func invalidateRoute() { resolved = nil }

    public var route: Route? { resolved?.route }

    // MARK: - Verbindung

    private func base() async throws -> (route: Route, url: URL) {
        if let resolved { return resolved }
        let candidates = endpoints.candidates
        guard !candidates.isEmpty else { throw VeloraError.notConfigured }
        var attempts: [String] = []
        for (route, url) in candidates {
            // Im fremden Netz läuft die Heim-IP ins Leere – kurz halten, damit Tailscale schnell dran ist.
            if let failure = await probe(url, timeout: route == .lan ? 2 : 10) {
                attempts.append("\(route.rawValue) \(url.absoluteString): \(failure)")
            } else {
                resolved = (route, url)
                return (route, url)
            }
        }
        throw VeloraError.unreachable(attempts)
    }

    /// `nil`, wenn der Server antwortet (auch 401 heisst: er ist da), sonst der Grund.
    private func probe(_ base: URL, timeout: TimeInterval) async -> String? {
        var request = URLRequest(url: base.appending(path: "api/refresh/status"), timeoutInterval: timeout)
        authorize(&request)
        do {
            _ = try await session.data(for: request)
            return nil
        } catch let error as URLError {
            switch error.code {
            case .timedOut: return "keine Antwort"
            case .cannotConnectToHost: return "Verbindung abgelehnt (Port?)"
            case .cannotFindHost, .dnsLookupFailed: return "Name unbekannt"
            case .notConnectedToInternet: return "kein Netz"
            case .appTransportSecurityRequiresSecureConnection: return "von iOS blockiert (HTTP)"
            default: return error.localizedDescription
            }
        } catch {
            return error.localizedDescription
        }
    }

    private func authorize(_ request: inout URLRequest) {
        if !password.isEmpty {
            request.setValue("velora_auth=\(password)", forHTTPHeaderField: "Cookie")
        }
    }

    private func makeRequest(_ path: String, method: String, body: Data?, timeout: TimeInterval) async throws -> URLRequest {
        let base = try await base().url
        guard let url = URL(string: base.absoluteString + (path.hasPrefix("/") ? path : "/" + path)) else {
            throw VeloraError.notConfigured
        }
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        authorize(&request)
        return request
    }

    /// Führt die Anfrage aus; reisst die Verbindung ab, wird die Route einmal neu bestimmt.
    private func perform(_ path: String, method: String = "GET", body: Data? = nil) async throws -> Data {
        for attempt in 0..<2 {
            let request = try await makeRequest(path, method: method, body: body, timeout: 45)
            do {
                let (data, response) = try await session.data(for: request)
                try Self.check(response, data: data)
                return data
            } catch is URLError where attempt == 0 {
                resolved = nil
            } catch let error as URLError {
                throw VeloraError.unreachable([error.localizedDescription])
            }
        }
        throw VeloraError.unreachable([])
    }

    private static func check(_ response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { throw VeloraError.unreachable([]) }
        if http.statusCode == 401 { throw VeloraError.unauthorized }
        guard (200..<300).contains(http.statusCode) else {
            struct Failure: Decodable { var error: String?; var detail: String? }
            let failure = try? JSONDecoder().decode(Failure.self, from: data)
            throw VeloraError.server(http.statusCode, failure?.error ?? failure?.detail ?? "")
        }
    }

    public static func decode<T: Decodable>(_ data: Data) throws -> T {
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch let DecodingError.keyNotFound(key, _) {
            throw VeloraError.decoding("fehlt: \(key.stringValue)")
        } catch {
            throw VeloraError.decoding(String(describing: type(of: T.self)))
        }
    }

    // MARK: - API

    public func get<T: Decodable>(_ path: String, as type: T.Type = T.self) async throws -> T {
        try Self.decode(try await perform(path))
    }

    /// Rohe Antwort, z. B. um sie für den Offline-Fall abzulegen.
    public func getData(_ path: String) async throws -> Data {
        try await perform(path)
    }

    @discardableResult
    public func post<T: Decodable>(_ path: String, body: some Encodable & Sendable, as type: T.Type = T.self) async throws -> T {
        try Self.decode(try await perform(path, method: "POST", body: try JSONEncoder().encode(body)))
    }

    @discardableResult
    public func send(_ path: String, method: String = "POST", body: [String: JSONValue] = [:]) async throws -> ActionResult {
        try Self.decode(try await perform(path, method: method, body: try JSONEncoder().encode(body)))
    }

    /// Chat-Nachricht senden und die Antwort Token für Token empfangen.
    public func chatStream(threadID: String, message: String) -> AsyncThrowingStream<ChatStreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let body = try JSONEncoder().encode(["message": message])
                    // Opus denkt mitunter lange nach, bevor das erste Token kommt.
                    let request = try await makeRequest("/api/chat/threads/\(threadID)/message",
                                                        method: "POST", body: body, timeout: 600)
                    let (bytes, response) = try await session.bytes(for: request)
                    if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                        var data = Data()
                        for try await byte in bytes { data.append(byte) }
                        try Self.check(response, data: data)
                    }
                    // `bytes.lines` verschluckt Leerzeilen, die SSE als Ereignisgrenze braucht – deshalb selbst trennen.
                    var parser = SSEParser()
                    var line: [UInt8] = []
                    for try await byte in bytes {
                        if byte == UInt8(ascii: "\n") {
                            if line.last == UInt8(ascii: "\r") { line.removeLast() }
                            if let raw = parser.feed(String(decoding: line, as: UTF8.self)),
                               let event = SSEParser.chatEvent(event: raw.event, data: raw.data) {
                                continuation.yield(event)
                            }
                            line.removeAll(keepingCapacity: true)
                        } else {
                            line.append(byte)
                        }
                    }
                    continuation.finish()
                } catch let error as URLError where error.code != .cancelled {
                    continuation.finish(throwing: VeloraError.unreachable([error.localizedDescription]))
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

extension JSONValue: ExpressibleByStringLiteral, ExpressibleByFloatLiteral, ExpressibleByIntegerLiteral, ExpressibleByBooleanLiteral {
    public init(stringLiteral value: String) { self = .string(value) }
    public init(floatLiteral value: Double) { self = .number(value) }
    public init(integerLiteral value: Int) { self = .number(Double(value)) }
    public init(booleanLiteral value: Bool) { self = .bool(value) }

    public init(_ value: String?) { self = value.map(JSONValue.string) ?? .null }
    public init(_ value: Double?) { self = value.map(JSONValue.number) ?? .null }
}
