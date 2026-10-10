import Foundation

/// Ein Briefing, zerlegt in Abschnitte.
///
/// Der Server schreibt Briefings als Telegram-HTML (`<b>`, `<i>`, `<code>`, `•`-Listen),
/// gegliedert in nummerierte Abschnitte wie `<b>1. MARKTLAGE</b>` oder `<b>2b) STOP-CHECK</b>`.
/// Ältere oder handgeschriebene Texte nutzen Markdown (`**fett**`, `## Titel`) – beides wird erkannt.
public struct BriefingDocument: Sendable, Hashable {
    public var title: String?
    public var sections: [BriefingSection]

    public init(title: String?, sections: [BriefingSection]) {
        self.title = title
        self.sections = sections
    }

    public static func parse(_ text: String) -> BriefingDocument {
        var title: String?
        var sections: [BriefingSection] = []
        var current: BriefingSection?
        var paragraph: [InlineRun] = []

        func flushParagraph() {
            guard !paragraph.isEmpty else { return }
            if current == nil { current = BriefingSection(number: nil, title: "Überblick") }
            current?.blocks.append(.paragraph(paragraph))
            paragraph = []
        }
        func startSection(_ section: BriefingSection) {
            flushParagraph()
            if let current, !current.blocks.isEmpty || current.number != nil { sections.append(current) }
            current = section
        }

        for raw in text.components(separatedBy: .newlines) {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.isEmpty { flushParagraph(); continue }

            if let heading = Self.heading(line) {
                if heading.number == nil, title == nil, sections.isEmpty, current == nil {
                    title = heading.title
                    continue
                }
                // Mitten im Text zählt eine fette Zeile ohne Nummer nur als Abschnitt, wenn sie
                // eindeutig ein Titel ist (## … oder GROSSBUCHSTABEN) – sonst ist sie betonter Text.
                if heading.number != nil || heading.strong {
                    startSection(BriefingSection(number: heading.number, title: heading.title))
                    continue
                }
            }
            if line == "---" || line == "***" || line == "———" { flushParagraph(); continue }

            if let rest = Self.bulletBody(line) {
                flushParagraph()
                if current == nil { current = BriefingSection(number: nil, title: "Überblick") }
                current?.blocks.append(.bullet(InlineRun.parse(rest)))
            } else if let (number, rest) = Self.numberedItem(line) {
                flushParagraph()
                if current == nil { current = BriefingSection(number: nil, title: "Überblick") }
                current?.blocks.append(.numbered(number, InlineRun.parse(rest)))
            } else {
                if !paragraph.isEmpty { paragraph.append(InlineRun(text: "\n")) }
                paragraph.append(contentsOf: InlineRun.parse(line))
            }
        }
        flushParagraph()
        if let current, !current.blocks.isEmpty || current.number != nil { sections.append(current) }
        return BriefingDocument(title: title, sections: sections)
    }

    // MARK: - Zeilenformen

    /// Eine Zeile, die nur aus einem fetten Titel besteht (`<b>1. MARKTLAGE</b>`, `**2) Portfolio**`,
    /// `## Risiken`). Nummer optional – ohne Nummer gilt sie nur ganz oben als Dokumenttitel.
    static func heading(_ line: String) -> (number: String?, title: String, strong: Bool)? {
        var inner: String
        if line.hasPrefix("#") {
            inner = String(line.drop { $0 == "#" }).trimmingCharacters(in: .whitespaces)
        } else if let unwrapped = unwrapBold(line) {
            inner = unwrapped
        } else {
            return nil
        }
        inner = InlineRun.plain(inner).trimmingCharacters(in: .whitespaces)
        guard !inner.isEmpty, inner.count <= 80 else { return nil }
        if let match = inner.firstMatch(of: /^(\d{1,2}[a-z]?)[.)]\s+(.+)$/) {
            return (String(match.1), String(match.2).trimmingCharacters(in: .whitespaces), true)
        }
        // Fette Zeile ohne Nummer: nur als Titel brauchbar, wenn sie kurz ist und kein Satz.
        if line.hasPrefix("#") || (!inner.hasSuffix(".") && !inner.hasSuffix(":")) {
            let letters = inner.filter(\.isLetter)
            let upper = !letters.isEmpty && letters.allSatisfy { $0.isUppercase }
            return (nil, inner, line.hasPrefix("#") || upper)
        }
        return nil
    }

    /// Inhalt, wenn die ganze Zeile in genau einem `<b>…</b>` bzw. `**…**` steckt.
    private static func unwrapBold(_ line: String) -> String? {
        for (open, close) in [("<b>", "</b>"), ("<strong>", "</strong>"), ("**", "**")] {
            guard line.hasPrefix(open), line.hasSuffix(close), line.count > open.count + close.count else { continue }
            let inner = String(line.dropFirst(open.count).dropLast(close.count))
            if !inner.contains(open) && !inner.contains(close) { return inner }
        }
        return nil
    }

    private static func bulletBody(_ line: String) -> String? {
        for marker in ["• ", "- ", "* ", "– ", "· "] where line.hasPrefix(marker) {
            return String(line.dropFirst(marker.count)).trimmingCharacters(in: .whitespaces)
        }
        if line.hasPrefix("•") { return String(line.dropFirst()).trimmingCharacters(in: .whitespaces) }
        return nil
    }

    private static func numberedItem(_ line: String) -> (String, String)? {
        guard let match = line.firstMatch(of: /^(\d{1,2})[.)]\s+(.+)$/) else { return nil }
        return (String(match.1), String(match.2))
    }
}

public struct BriefingSection: Sendable, Hashable, Identifiable {
    public enum Kind: Sendable, Hashable {
        case market, portfolio, stops, events, recommendations, ideas, risks, track, other
    }

    public var id: String { (number ?? "") + title }
    public var number: String?
    public var title: String
    public var blocks: [BriefingBlock] = []

    public init(number: String?, title: String, blocks: [BriefingBlock] = []) {
        self.number = number
        self.title = title
        self.blocks = blocks
    }

    /// Titel ohne Zusatz („MARKTLAGE — unruhig“ → „Marktlage“), in normaler Schreibung.
    public var displayTitle: String {
        let base = title.components(separatedBy: " — ").first ?? title
        let cleaned = base.trimmingCharacters(in: CharacterSet(charactersIn: " :–-"))
        // GROSSBUCHSTABEN-Titel lesbar machen, gemischte Schreibung unverändert lassen.
        guard cleaned == cleaned.uppercased() else { return cleaned }
        let keepUpper: Set<String> = ["ETF", "KI", "AI", "USA", "US", "EU", "EZB", "FED", "KEST"]
        return cleaned.split(separator: " ").map { word in
            let w = String(word)
            if keepUpper.contains(w) { return w }
            return w.split(separator: "-", omittingEmptySubsequences: false)
                .map { $0.prefix(1) + $0.dropFirst().lowercased() }.joined(separator: "-")
        }.joined(separator: " ").replacingOccurrences(of: " & ", with: " & ")
    }

    /// Zusatz nach dem Gedankenstrich im Titel, z. B. „unruhig“.
    public var subtitle: String? {
        let parts = title.components(separatedBy: " — ")
        return parts.count > 1 ? parts.dropFirst().joined(separator: " — ") : nil
    }

    public var kind: Kind {
        let t = title.lowercased()
        if t.contains("bilanz") { return .track }
        if t.contains("empfehlung") { return .recommendations }
        if t.contains("stop") { return .stops }
        if t.contains("markt") { return .market }
        if t.contains("portfolio") || t.contains("depot") { return .portfolio }
        if t.contains("earnings") || t.contains("termin") || t.contains("event") { return .events }
        if t.contains("idee") { return .ideas }
        if t.contains("risik") { return .risks }
        return .other
    }

    /// Reiner Text des ersten Blocks – Vorschau für eingeklappte Abschnitte.
    public var preview: String {
        guard let first = blocks.first else { return "" }
        return InlineRun.plainText(first.runs)
    }

    public var characterCount: Int { blocks.reduce(0) { $0 + InlineRun.plainText($1.runs).count } }
}

public enum BriefingBlock: Sendable, Hashable {
    case paragraph([InlineRun])
    case bullet([InlineRun])
    case numbered(String, [InlineRun])

    public var runs: [InlineRun] {
        switch self {
        case .paragraph(let r), .bullet(let r), .numbered(_, let r): r
        }
    }
}

/// Textstück mit einheitlicher Auszeichnung.
public struct InlineRun: Sendable, Hashable {
    public var text: String
    public var bold = false
    public var italic = false
    public var code = false
    /// Quellen-Markierung wie „[Fakt]“ oder „[Einschätzung]“ – wird dezent dargestellt.
    public var tag = false

    public init(text: String, bold: Bool = false, italic: Bool = false, code: Bool = false, tag: Bool = false) {
        self.text = text
        self.bold = bold
        self.italic = italic
        self.code = code
        self.tag = tag
    }

    public static func plainText(_ runs: [InlineRun]) -> String { runs.map(\.text).joined() }

    /// Entfernt alle Auszeichnungen.
    public static func plain(_ s: String) -> String { plainText(parse(s)) }

    /// Zerlegt eine Zeile mit Telegram-HTML bzw. Markdown in Textstücke.
    public static func parse(_ s: String) -> [InlineRun] {
        var runs: [InlineRun] = []
        var bold = 0, italic = 0, code = 0
        var buffer = ""

        func flush() {
            guard !buffer.isEmpty else { return }
            runs.append(contentsOf: splitTags(decodeEntities(buffer), bold: bold > 0, italic: italic > 0, code: code > 0))
            buffer = ""
        }

        var i = s.startIndex
        while i < s.endIndex {
            let rest = s[i...]
            if rest.hasPrefix("<"), let match = rest.prefixMatch(of: /<(\/?)([a-zA-Z]+)[^>]*>/) {
                flush()
                let closing = !match.1.isEmpty
                let delta = closing ? -1 : 1
                switch match.2.lowercased() {
                case "b", "strong": bold = max(0, bold + delta)
                case "i", "em": italic = max(0, italic + delta)
                case "code", "pre": code = max(0, code + delta)
                case "br": buffer += "\n"
                default: break  // u, s, a, span … : Text behalten, Tag verwerfen
                }
                i = match.range.upperBound
            } else if rest.hasPrefix("**") {
                flush()
                bold = bold > 0 ? 0 : 1
                i = s.index(i, offsetBy: 2)
            } else if rest.hasPrefix("`") {
                flush()
                code = code > 0 ? 0 : 1
                i = s.index(after: i)
            } else {
                buffer.append(s[i])
                i = s.index(after: i)
            }
        }
        flush()
        return merge(runs)
    }

    private static func decodeEntities(_ s: String) -> String {
        guard s.contains("&") else { return s }
        var out = s
        for (entity, char) in [("&lt;", "<"), ("&gt;", ">"), ("&quot;", "\""), ("&#39;", "'"), ("&#x27;", "'"),
                               ("&apos;", "'"), ("&nbsp;", "\u{00A0}"), ("&amp;", "&")] {
            out = out.replacingOccurrences(of: entity, with: char)
        }
        return out
    }

    /// Hebt „[Fakt]“, „[Einschätzung]“ usw. als eigene Stücke heraus.
    private static func splitTags(_ s: String, bold: Bool, italic: Bool, code: Bool) -> [InlineRun] {
        var result: [InlineRun] = []
        var remaining = Substring(s)
        let pattern = /\[(?:Fakt|Einschätzung|Annahme|Meinung|Quelle)[^\]]{0,40}\]/
        while let match = remaining.firstMatch(of: pattern) {
            let before = remaining[..<match.range.lowerBound]
            if !before.isEmpty { result.append(InlineRun(text: String(before), bold: bold, italic: italic, code: code)) }
            let label = String(match.output.dropFirst().dropLast())
            result.append(InlineRun(text: label, tag: true))
            remaining = remaining[match.range.upperBound...]
        }
        if !remaining.isEmpty { result.append(InlineRun(text: String(remaining), bold: bold, italic: italic, code: code)) }
        return result
    }

    private static func merge(_ runs: [InlineRun]) -> [InlineRun] {
        var out: [InlineRun] = []
        for run in runs where !run.text.isEmpty {
            if var last = out.last, last.bold == run.bold, last.italic == run.italic, last.code == run.code,
               !last.tag, !run.tag {
                last.text += run.text
                out[out.count - 1] = last
            } else {
                out.append(run)
            }
        }
        return out
    }
}
