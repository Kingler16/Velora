import Foundation

/// Zahlen und Daten im österreichischen Format (1.234,56 €, +2,7 %).
public enum Format {
    public static let locale = Locale(identifier: "de_AT")

    public static func eur(_ value: Double?, digits: Int = 2) -> String {
        guard let value else { return "–" }
        return value.formatted(.currency(code: "EUR").locale(locale).precision(.fractionLength(digits)))
    }

    /// Mit Vorzeichen, für Gewinn/Verlust.
    public static func signedEur(_ value: Double?, digits: Int = 2) -> String {
        guard let value else { return "–" }
        return value.formatted(.currency(code: "EUR").locale(locale).precision(.fractionLength(digits))
            .sign(strategy: .accountingAlways(showZero: false)))
            .replacingOccurrences(of: "(", with: "−").replacingOccurrences(of: ")", with: "")
    }

    /// Kurzform für Diagrammachsen: 56 Tsd. €
    public static func eurShort(_ value: Double) -> String {
        if abs(value) >= 1_000 {
            return (value / 1_000).formatted(.number.locale(locale).precision(.fractionLength(0...1))) + " Tsd. €"
        }
        return eur(value, digits: 0)
    }

    /// Preis in seiner Notierungswährung.
    public static func price(_ value: Double?, currency: String) -> String {
        guard let value else { return "–" }
        let code = currency == "GBp" ? "GBP" : currency
        let digits = value < 10 ? 3 : 2
        return value.formatted(.currency(code: code).locale(locale).precision(.fractionLength(2...digits)))
    }

    /// Prozentwert (19.5 → „+19,5 %“).
    public static func pct(_ value: Double?, digits: Int = 1, signed: Bool = true) -> String {
        guard let value else { return "–" }
        let style = FloatingPointFormatStyle<Double>.Percent.percent.locale(locale)
            .precision(.fractionLength(digits))
        return (value / 100).formatted(signed ? style.sign(strategy: .always(includingZero: false)) : style)
    }

    public static func number(_ value: Double?, digits: Int = 2) -> String {
        guard let value else { return "–" }
        return value.formatted(.number.locale(locale).precision(.fractionLength(0...digits)))
    }

    /// Für Eingabefelder: ohne Tausenderpunkt, damit die Zahl wieder eindeutig einlesbar ist.
    public static func plain(_ value: Double, digits: Int = 4) -> String {
        value.formatted(.number.locale(locale).grouping(.never).precision(.fractionLength(0...digits)))
    }

    public static func shares(_ value: Double) -> String {
        value.formatted(.number.locale(locale).precision(.fractionLength(0...4)))
    }

    public static func date(_ string: String?, time: Bool = false) -> String {
        guard let date = VeloraDate.parse(string) else { return string ?? "–" }
        var style = Date.FormatStyle(date: .abbreviated, time: time ? .shortened : .omitted).locale(locale)
        style.timeZone = .current
        return date.formatted(style)
    }

    /// „vor 3 Std.“
    public static func relative(_ string: String?) -> String {
        guard let date = VeloraDate.parse(string) else { return string ?? "" }
        return date.formatted(.relative(presentation: .named).locale(locale))
    }

    /// Alter des Daten-Caches in Minuten, lesbar.
    public static func age(minutes: Double?) -> String {
        guard let minutes else { return "unbekannt" }
        if minutes < 1 { return "gerade eben" }
        if minutes < 60 { return "vor \(Int(minutes)) min" }
        if minutes < 60 * 48 { return "vor \(Int(minutes / 60)) Std." }
        return "vor \(Int(minutes / 60 / 24)) Tagen"
    }

    /// Kontoschlüssel lesbar machen: `scalable_capital` → „Scalable Capital“.
    public static func accountName(_ key: String) -> String {
        key.split(separator: "_").map { $0.prefix(1).uppercased() + $0.dropFirst() }.joined(separator: " ")
    }

    public static let weekdays: [(key: String, label: String)] = [
        ("monday", "Mo"), ("tuesday", "Di"), ("wednesday", "Mi"), ("thursday", "Do"),
        ("friday", "Fr"), ("saturday", "Sa"), ("sunday", "So"),
    ]
}
