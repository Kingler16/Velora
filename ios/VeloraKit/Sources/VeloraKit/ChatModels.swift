import Foundation

public struct ChatThread: Decodable, Sendable, Identifiable, Hashable {
    public var id: String
    public var title: String
    public var updatedAt: String?
    public var messageCount: Int
    public var isPinned: Bool

    enum CodingKeys: String, CodingKey {
        case id, title
        case updatedAt = "updated_at", messageCount = "message_count", isPinned = "is_pinned"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = c(.title, default: "Neuer Chat")
        updatedAt = c(.updatedAt)
        messageCount = c(.messageCount, default: 0)
        isPinned = c.flag(.isPinned)
    }
}

/// Werkzeugaufruf des Velora-Agenten (z. B. Watchlist ändern).
public struct ToolCall: Decodable, Sendable, Hashable {
    public var id: String?
    public var name: String
    public var input: [String: JSONValue]

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c(.id)
        name = c(.name, default: "")
        input = c(.input, default: [:])
    }

    enum CodingKeys: String, CodingKey { case id, name, input }

    /// `mcp__velora__update_watchlist` → „Update watchlist“
    public var label: String {
        let short = name.replacingOccurrences(of: "mcp__velora__", with: "").replacingOccurrences(of: "_", with: " ")
        return short.prefix(1).uppercased() + short.dropFirst()
    }
}

public struct ChatMessage: Decodable, Sendable, Identifiable, Hashable {
    public enum Role: String, Sendable { case user, assistant, toolUse = "tool_use", other }

    public var id: String
    public var role: Role
    public var content: String
    public var createdAt: String?
    public var tool: ToolCall?

    enum CodingKeys: String, CodingKey { case id, role, content, createdAt = "created_at" }

    public init(id: String = UUID().uuidString, role: Role, content: String, tool: ToolCall? = nil) {
        self.id = id
        self.role = role
        self.content = content
        self.tool = tool
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        if let int: Int = c(.id) { id = String(int) } else { id = c(.id, default: UUID().uuidString) }
        role = Role(rawValue: c(.role, default: "")) ?? .other
        content = c(.content, default: "")
        createdAt = c(.createdAt)
        if role == .toolUse, let data = content.data(using: .utf8) {
            tool = try? JSONDecoder().decode(ToolCall.self, from: data)
        }
    }
}

public struct ThreadDetail: Decodable, Sendable {
    public var thread: ChatThread
    public var messages: [ChatMessage]
}

/// Antwort auf `POST /api/chat/confirm`.
public struct ConfirmResult: Decodable, Sendable {
    public var success: Bool
    public var message: String

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        success = c.flag(.success)
        message = c(.message, default: "")
    }

    enum CodingKeys: String, CodingKey { case success, message }
}

public struct ThreadList: Decodable, Sendable {
    public var threads: [ChatThread]
}

/// Schreibaktion des Agenten, die erst nach Bestätigung ausgeführt wird.
public struct PendingConfirmation: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { actionId }
    public var actionId: String
    public var summary: String
    public var toolName: String?
    public var params: [String: JSONValue]

    enum CodingKeys: String, CodingKey {
        case summary, params, id
        case actionId = "action_id", toolName = "tool_name"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        // Im Stream heisst das Feld action_id, in /api/chat/pending ist es die Zeilen-ID.
        guard let id: String = c(.actionId) ?? c(.id) else {
            throw DecodingError.keyNotFound(CodingKeys.actionId, .init(codingPath: decoder.codingPath, debugDescription: "action_id fehlt"))
        }
        actionId = id
        summary = c(.summary, default: "")
        toolName = c(.toolName)
        params = c(.params, default: [:])
    }
}

/// Ein Ereignis aus dem SSE-Stream von `POST /api/chat/threads/{id}/message`.
public enum ChatStreamEvent: Sendable {
    case token(String)
    case toolUse(ToolCall)
    case confirmationRequired(PendingConfirmation)
    case done
    case error(String)
}

/// Zerlegt Server-Sent-Events zeilenweise. Ein Ereignis endet mit einer Leerzeile.
public struct SSEParser: Sendable {
    private var event = "message"
    private var data: [String] = []

    public init() {}

    /// Nimmt eine Zeile (ohne Zeilenumbruch) entgegen und liefert ein fertiges Ereignis, sobald es komplett ist.
    public mutating func feed(_ line: String) -> (event: String, data: String)? {
        if line.isEmpty {
            defer { event = "message"; data = [] }
            return data.isEmpty ? nil : (event, data.joined(separator: "\n"))
        }
        if line.hasPrefix(":") { return nil }
        let (field, value) = Self.split(line)
        switch field {
        case "event": event = value
        case "data": data.append(value)
        default: break
        }
        return nil
    }

    private static func split(_ line: String) -> (String, String) {
        guard let colon = line.firstIndex(of: ":") else { return (line, "") }
        var value = line[line.index(after: colon)...]
        if value.first == " " { value = value.dropFirst() }
        return (String(line[..<colon]), String(value))
    }

    /// Übersetzt ein rohes SSE-Ereignis des Velora-Chats.
    public static func chatEvent(event: String, data: String) -> ChatStreamEvent? {
        let json = Data(data.utf8)
        let decoder = JSONDecoder()
        struct Text: Decodable { var text: String?; var message: String? }
        switch event {
        case "token":
            return (try? decoder.decode(Text.self, from: json))?.text.map(ChatStreamEvent.token)
        case "tool_use":
            return (try? decoder.decode(ToolCall.self, from: json)).map(ChatStreamEvent.toolUse)
        case "confirmation_required":
            return (try? decoder.decode(PendingConfirmation.self, from: json)).map(ChatStreamEvent.confirmationRequired)
        case "done":
            return .done
        case "error", "fatal":
            return .error((try? decoder.decode(Text.self, from: json))?.message ?? "Chat fehlgeschlagen")
        default:
            return nil
        }
    }
}
