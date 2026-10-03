import Foundation

/// Nachsichtiges Dekodieren: Der Server ist Python, Felder fehlen oder sind
/// `null`, Zahlen kommen mal als Int, mal als Float. Statt die ganze Antwort an
/// einem fehlenden Feld scheitern zu lassen, fällt jedes Feld auf einen Default.
extension KeyedDecodingContainer {
    func callAsFunction<T: Decodable>(_ key: Key, default value: T) -> T {
        (try? decodeIfPresent(T.self, forKey: key)) ?? value
    }

    func callAsFunction<T: Decodable>(_ key: Key) -> T? {
        (try? decodeIfPresent(T.self, forKey: key)) ?? nil
    }

    /// SQLite liefert Wahrheitswerte als 0/1.
    func flag(_ key: Key) -> Bool {
        if let bool = try? decodeIfPresent(Bool.self, forKey: key) { return bool }
        if let int = try? decodeIfPresent(Int.self, forKey: key) { return int != 0 }
        return false
    }
}

/// Beliebiger JSON-Wert – für Felder, deren Form vom Server frei gewählt wird
/// (Tool-Parameter im Chat, Ausnahmen in Mandatsregeln).
public enum JSONValue: Codable, Sendable, Hashable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case array([JSONValue])
    case object([String: JSONValue])
    case null

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([JSONValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }

    /// Kurze, lesbare Darstellung für die Anzeige.
    public var display: String {
        switch self {
        case .string(let v): v
        case .number(let v): v.rounded() == v && abs(v) < 1e15 ? String(Int(v)) : String(v)
        case .bool(let v): v ? "ja" : "nein"
        case .array(let v): v.map(\.display).joined(separator: ", ")
        case .object(let v): v.sorted { $0.key < $1.key }.map { "\($0.key): \($0.value.display)" }.joined(separator: ", ")
        case .null: "–"
        }
    }
}

/// Zeitstempel kommen in mehreren Formaten: ISO mit Mikrosekunden ohne Zone
/// (Serverzeit Wien), reines Datum, ISO mit Zone (git) und RFC 1123 (RSS).
public enum VeloraDate {
    public static let serverTimeZone = TimeZone(identifier: "Europe/Vienna")!

    private static let localFormatters: [DateFormatter] = [
        "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd", "dd.MM.yyyy HH:mm",
    ].map { format in
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = serverTimeZone
        f.dateFormat = format
        return f
    }

    private static let rfc1123: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "EEE, dd MMM yyyy HH:mm:ss zzz"
        return f
    }()

    public static func parse(_ string: String?) -> Date? {
        guard var s = string?.trimmingCharacters(in: .whitespaces), !s.isEmpty else { return nil }
        if let date = try? Date(s, strategy: .iso8601) { return date }
        if s.count > 10, s.dropFirst(10).first == "T" || s.dropFirst(10).first == " ",
           s.last != "Z", !s.dropFirst(19).contains("+") {
            s = String(s.prefix(19))  // Mikrosekunden abschneiden
        }
        for f in localFormatters { if let d = f.date(from: s) { return d } }
        return rfc1123.date(from: s)
    }
}
