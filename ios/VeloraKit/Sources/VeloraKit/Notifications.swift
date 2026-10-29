import Foundation

/// Wohin ein Tipp auf eine Mitteilung führt – aus dem `url`-Feld, das der Server
/// mitschickt (dieselben Pfade wie in der Web-App).
public enum PushTarget: Equatable, Sendable {
    case dashboard
    case portfolio
    case briefings
    case recommendations
    case chat(threadID: String?)

    public init(url: String?) {
        let components = URLComponents(string: url ?? "/")
        let path = components?.path ?? "/"
        switch path {
        case "/portfolio", "/strategy", "/holdings": self = .portfolio
        case "/briefings": self = .briefings
        case "/recommendations": self = .recommendations
        case "/chat":
            let id = components?.queryItems?.first { $0.name == "thread" }?.value
            self = .chat(threadID: id?.isEmpty == false ? id : nil)
        default: self = .dashboard
        }
    }
}

/// Inhalt einer empfangenen Mitteilung, ohne die nicht-`Sendable` userInfo weiterzureichen.
public struct PushInfo: Equatable, Sendable {
    public var category: String?
    public var target: PushTarget

    public init(category: String?, url: String?) {
        self.category = category
        target = PushTarget(url: url)
    }

    public init(userInfo: [AnyHashable: Any]) {
        self.init(category: userInfo["category"] as? String, url: userInfo["url"] as? String)
    }

    public var chatThreadID: String? {
        if case .chat(let id) = target { id } else { nil }
    }
}

/// Ein Eintrag aus `GET /api/push/preferences`.
public struct NotificationPreference: Decodable, Sendable, Equatable {
    public var telegramEnabled: Bool
    public var pushEnabled: Bool

    enum CodingKeys: String, CodingKey {
        case telegramEnabled = "telegram_enabled", pushEnabled = "push_enabled"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        telegramEnabled = c.flag(.telegramEnabled)
        pushEnabled = c.flag(.pushEnabled)
    }
}

/// Kategorien, die die App zum Ein- und Ausschalten anbietet – in dieser Reihenfolge.
public enum NotificationCategory: String, CaseIterable, Identifiable, Sendable {
    case briefings
    case pendingAction = "pending_action"
    case chatReply = "chat_reply"
    case tradeConfirmed = "trade_confirmed"
    case recommendationClosed = "recommendation_closed"
    case systemError = "system_error"

    public var id: Self { self }

    public var title: String {
        switch self {
        case .briefings: "Briefings & Monatsreport"
        case .pendingAction: "Velora braucht dein OK"
        case .chatReply: "Chat-Antworten"
        case .tradeConfirmed: "Trade gebucht"
        case .recommendationClosed: "Empfehlung geschlossen"
        case .systemError: "Systemfehler"
        }
    }
}
