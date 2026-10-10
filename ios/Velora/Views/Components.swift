import SwiftUI
import VeloraKit

/// Velora-Farben aus dem Web-Design-System (design-system.css).
enum Theme {
    static let accent = Color(hex: 0x3B82F6)
    static let cyan = Color(hex: 0x22D3EE)
    static let indigo = Color(hex: 0x6366F1)
    static let violet = Color(hex: 0x8B5CF6)
    static let amber = Color(hex: 0xFBBF24)
    static let gain = Color(hex: 0x34D399)
    static let loss = Color(hex: 0xF87171)
    static let background = Color(hex: 0x0D1117)

    /// Kategoriefarben für Diagramme (Positionen, Regionen, Sektoren).
    static let series: [Color] = [
        Color(hex: 0x3B82F6), Color(hex: 0x22D3EE), Color(hex: 0x8B5CF6), Color(hex: 0x34D399),
        Color(hex: 0xFBBF24), Color(hex: 0xF472B6), Color(hex: 0x6366F1), Color(hex: 0xFB923C),
        Color(hex: 0x94A3B8),
    ]

    static func change(_ value: Double?) -> Color {
        guard let value, value != 0 else { return .secondary }
        return value > 0 ? gain : loss
    }

    static func severity(_ s: String) -> Color {
        switch s {
        case "breach", "block": loss
        case "warn": amber
        default: gain
        }
    }

    /// Grün bleibt Gewinnen vorbehalten – Kaufen ist deshalb Blau.
    static func action(_ action: String) -> Color {
        switch action {
        case "buy": accent
        case "sell": loss
        case "watch": amber
        default: violet
        }
    }

    static func actionIcon(_ rec: Recommendation) -> String {
        switch rec.action {
        case "buy": "cart.fill"
        case "sell": "arrow.down.right"
        case "watch": "eye.fill"
        case "hold" where rec.stopLoss != nil: rec.currentStop == nil ? "shield.lefthalf.filled" : "arrow.up.to.line"
        default: "pause.fill"
        }
    }

    /// Stop-Status: neutral, wenn alles passt; Gelb, wenn etwas zu tun ist.
    static func stopStatus(_ s: StopPosition) -> Color {
        if s.status == "ungueltig" { return loss }
        return s.needsAttention ? amber : cyan
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255)
    }
}

struct Card<Content: View>: View {
    var title: String?
    var subtitle: String?
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let title {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.headline)
                    if let subtitle {
                        Text(subtitle).font(.footnote).foregroundStyle(.secondary)
                    }
                }
            }
            content
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.background.secondary, in: .rect(cornerRadius: 20))
    }
}

struct StatTile: View {
    var title: String
    var value: String
    var footnote: String?
    var footnoteColor: Color = .secondary

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.title3.weight(.semibold)).monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.6)
            if let footnote {
                Text(footnote).font(.caption2).foregroundStyle(footnoteColor).monospacedDigit()
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.background.secondary, in: .rect(cornerRadius: 16))
    }
}

/// Prozentveränderung mit Pfeil – die Farbe steht nie allein.
struct ChangeLabel: View {
    var pct: Double?
    var eur: Double?
    var font: Font = .subheadline

    var body: some View {
        HStack(spacing: 3) {
            if let pct, pct != 0 {
                Image(systemName: pct > 0 ? "arrowtriangle.up.fill" : "arrowtriangle.down.fill")
                    .font(.system(size: 8))
            }
            if let eur { Text(Format.signedEur(eur)) }
            if let pct { Text(eur == nil ? Format.pct(pct) : "(\(Format.pct(pct)))") }
        }
        .font(font.weight(.medium))
        .monospacedDigit()
        .foregroundStyle(Theme.change(pct ?? eur))
    }
}

struct Pill: View {
    var text: String
    var color: Color

    var body: some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .foregroundStyle(color)
            .background(color.opacity(0.15), in: .capsule)
    }
}

/// Kurs in Originalwährung, darunter klein der Euro-Gegenwert (nur bei Dollar-Kursen).
struct PriceStack: View {
    var value: Double?
    var currency: String
    var eurUsd: Double?
    var alignment: HorizontalAlignment = .trailing
    var font: Font = .subheadline.weight(.semibold)

    var body: some View {
        VStack(alignment: alignment, spacing: 1) {
            Text(Format.price(value, currency: currency)).font(font)
            if let hint = Format.eurHint(value, currency: currency, eurUsd: eurUsd) {
                Text(hint).font(.caption2).foregroundStyle(.secondary)
            }
        }
        .monospacedDigit()
    }
}

/// Runder Farbpunkt mit Symbol – Erkennungszeichen einer Aktion.
struct IconBadge: View {
    var systemImage: String
    var color: Color
    var size: CGFloat = 36

    var body: some View {
        Image(systemName: systemImage)
            .font(.system(size: size * 0.42, weight: .semibold))
            .foregroundStyle(color)
            .frame(width: size, height: size)
            .background(color.opacity(0.16), in: .circle)
    }
}

/// Waagrechter Anteilsbalken mit Beschriftung.
struct ShareBar: View {
    var label: String
    var pct: Double
    var detail: String?
    var color: Color = Theme.accent
    var maxPct: Double = 100

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(label).font(.subheadline).lineLimit(1)
                Spacer()
                if let detail { Text(detail).font(.caption).foregroundStyle(.secondary).monospacedDigit() }
                Text(Format.pct(pct, signed: false)).font(.subheadline.weight(.medium)).monospacedDigit()
            }
            GeometryReader { geo in
                Capsule().fill(.quaternary)
                    .overlay(alignment: .leading) {
                        Capsule().fill(color)
                            .frame(width: geo.size.width * min(max(pct / max(maxPct, 0.01), 0), 1))
                    }
            }
            .frame(height: 6)
        }
    }
}

/// Lädt eine Ansicht vom Server, zeigt bei Verbindungsproblemen den letzten Stand.
///
/// Solange geladen wird, steht der zwischengespeicherte Stand mit „Aktualisiere …“ da –
/// „Offline“ erscheint erst, wenn der Server wirklich nicht antwortet. Danach versucht die
/// Ansicht es von selbst wieder (mit wachsendem Abstand), solange sie sichtbar ist.
struct RemoteView<T: Decodable, Content: View>: View {
    var path: String
    @ViewBuilder var content: (T) -> Content

    @Environment(AppModel.self) private var model
    @State private var value: T?
    @State private var error: Error?
    @State private var cachedAt: Date?
    @State private var loading = false
    @State private var failures = 0

    var body: some View {
        Group {
            if let value {
                content(value)
                    .safeAreaInset(edge: .top, spacing: 0) {
                        if let cachedAt, loading || error != nil {
                            StaleBanner(since: cachedAt, error: error, loading: loading) { Task { await load() } }
                        }
                    }
            } else if let error {
                ContentUnavailableView {
                    Label(LoadError.title(for: error), systemImage: LoadError.icon(for: error))
                } description: {
                    Text(error.localizedDescription)
                } actions: {
                    Button("Erneut versuchen") { Task { await load() } }
                        .buttonStyle(.borderedProminent)
                        .disabled(loading)
                }
            } else {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task(id: model.reloadToken) {
            await load()
            // Automatisch erneut versuchen, solange der Server nicht erreichbar ist.
            while error != nil, !Task.isCancelled {
                let delay = min(10 * (1 << min(max(failures - 1, 0), 3)), 60)
                try? await Task.sleep(for: .seconds(delay))
                if Task.isCancelled { break }
                await load()
            }
        }
        .refreshable { await load() }
    }

    private func load() async {
        if value == nil, let cached = model.cached(path, as: T.self) {
            value = cached.value
            cachedAt = cached.date
        }
        loading = true
        defer { loading = false }
        do {
            value = try await model.load(path)
            error = nil
            failures = 0
            cachedAt = .now
        } catch is CancellationError {
        } catch where Task.isCancelled {
            // Tab gewechselt oder neu geladen – der nächste Ladevorgang übernimmt.
        } catch {
            self.error = error
            failures += 1
            if value != nil, cachedAt == nil { cachedAt = .now }
        }
    }
}

/// Überschrift und Symbol je Fehlerart – unterscheidet „offline“ von „Server kaputt“.
enum LoadError {
    static func title(for error: Error) -> String {
        switch error as? VeloraError {
        case .server: "Serverfehler"
        case .unauthorized: "Anmeldung nötig"
        case .decoding: "Unerwartete Antwort"
        case .notConfigured: "Kein Server eingetragen"
        default: "Keine Verbindung"
        }
    }

    static func icon(for error: Error) -> String {
        switch error as? VeloraError {
        case .server, .decoding: "exclamationmark.triangle"
        case .unauthorized: "lock"
        default: "wifi.exclamationmark"
        }
    }
}

struct StaleBanner: View {
    var since: Date
    var error: Error?
    var loading: Bool
    var retry: () -> Void

    @State private var showDetail = false

    var body: some View {
        Button {
            if error != nil { showDetail = true }
        } label: {
            HStack(spacing: 6) {
                if loading {
                    ProgressView().controlSize(.mini)
                    Text("Aktualisiere …")
                } else if let error {
                    Image(systemName: LoadError.icon(for: error))
                    Text(label(for: error))
                }
            }
            .font(.footnote.weight(.medium))
            .foregroundStyle(loading ? Color.secondary : Theme.amber)
            .padding(.vertical, 6)
            .padding(.horizontal, 12)
            .background(.ultraThinMaterial, in: .capsule)
        }
        .buttonStyle(.plain)
        .padding(.top, 4)
        .alert(error.map { LoadError.title(for: $0) } ?? "", isPresented: $showDetail) {
            Button("Erneut versuchen", action: retry)
            Button("OK", role: .cancel) {}
        } message: {
            Text(error?.localizedDescription ?? "")
        }
    }

    private func label(for error: Error) -> String {
        let age = since.formatted(.relative(presentation: .named).locale(Format.locale))
        if case .server = error as? VeloraError { return "Serverfehler – Stand \(age)" }
        return "Offline – Stand \(age)"
    }
}

/// Einfacher Markdown-Renderer für Briefings und Chat: Überschriften, Listen, Fettschrift, Links.
struct MarkdownText: View {
    var text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                switch block {
                case .heading(let level, let s):
                    Text(inline(s))
                        .font(level <= 1 ? .title3.bold() : level == 2 ? .headline : .subheadline.bold())
                        .padding(.top, 6)
                case .bullet(let s):
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("•").foregroundStyle(.secondary)
                        Text(inline(s))
                    }
                case .paragraph(let s):
                    Text(inline(s))
                case .rule:
                    Divider()
                }
            }
        }
        .textSelection(.enabled)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private enum Block { case heading(Int, String), bullet(String), paragraph(String), rule }

    private var blocks: [Block] {
        var result: [Block] = []
        var paragraph: [String] = []
        func flush() {
            if !paragraph.isEmpty { result.append(.paragraph(paragraph.joined(separator: "\n"))) }
            paragraph = []
        }
        for raw in text.components(separatedBy: .newlines) {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.isEmpty { flush(); continue }
            if line.hasPrefix("#") {
                flush()
                let level = line.prefix { $0 == "#" }.count
                result.append(.heading(level, String(line.dropFirst(level)).trimmingCharacters(in: .whitespaces)))
            } else if line.hasPrefix("- ") || line.hasPrefix("* ") || line.hasPrefix("• ") {
                flush()
                result.append(.bullet(String(line.dropFirst(2))))
            } else if line == "---" || line == "***" {
                flush()
                result.append(.rule)
            } else if line == line.uppercased(), line.count > 3, line.count < 50, line.rangeOfCharacter(from: .letters) != nil {
                // Briefings nutzen GROSSBUCHSTABEN-Zeilen als Abschnittstitel.
                flush()
                result.append(.heading(2, line.capitalized(with: Format.locale)))
            } else {
                paragraph.append(line)
            }
        }
        flush()
        return result
    }

    private func inline(_ s: String) -> AttributedString {
        (try? AttributedString(markdown: s, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
            ?? AttributedString(s)
    }
}

/// Fehlermeldung als Alert.
struct ErrorAlert: ViewModifier {
    @Binding var error: String?

    func body(content: Content) -> some View {
        content.alert("Fehler", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(error ?? "")
        }
    }
}

extension View {
    func errorAlert(_ error: Binding<String?>) -> some View { modifier(ErrorAlert(error: error)) }
}

/// Zahleneingabe mit Komma oder Punkt.
func parseNumber(_ s: String) -> Double? {
    let cleaned = s.trimmingCharacters(in: .whitespaces)
        .replacingOccurrences(of: ".", with: s.contains(",") ? "" : ".")
        .replacingOccurrences(of: ",", with: ".")
    return Double(cleaned)
}
