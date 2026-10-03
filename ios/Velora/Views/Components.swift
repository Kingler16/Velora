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

    static func action(_ action: String) -> Color {
        switch action {
        case "buy": gain
        case "sell": loss
        case "watch": amber
        default: cyan
        }
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
struct RemoteView<T: Decodable, Content: View>: View {
    var path: String
    @ViewBuilder var content: (T) -> Content

    @Environment(AppModel.self) private var model
    @State private var value: T?
    @State private var error: Error?
    @State private var staleSince: Date?

    var body: some View {
        Group {
            if let value {
                content(value)
                    .safeAreaInset(edge: .top, spacing: 0) {
                        if let staleSince { StaleBanner(since: staleSince, error: error) }
                    }
            } else if let error {
                ContentUnavailableView {
                    Label("Keine Verbindung", systemImage: "wifi.exclamationmark")
                } description: {
                    Text(error.localizedDescription)
                } actions: {
                    Button("Erneut versuchen") { Task { await load() } }
                        .buttonStyle(.borderedProminent)
                }
            } else {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task(id: model.reloadToken) { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        if value == nil, let cached = model.cached(path, as: T.self) {
            value = cached.value
            staleSince = cached.date
        }
        do {
            value = try await model.load(path)
            error = nil
            staleSince = nil
        } catch is CancellationError {
        } catch where Task.isCancelled {
            // Tab gewechselt oder neu geladen – der nächste Ladevorgang übernimmt.
        } catch {
            self.error = error
            if value != nil, staleSince == nil { staleSince = .now }
        }
    }
}

struct StaleBanner: View {
    var since: Date
    var error: Error?

    var body: some View {
        Label {
            Text("Offline – Stand \(since.formatted(.relative(presentation: .named).locale(Format.locale)))")
        } icon: {
            Image(systemName: "icloud.slash")
        }
        .font(.footnote.weight(.medium))
        .foregroundStyle(Theme.amber)
        .padding(.vertical, 6)
        .padding(.horizontal, 12)
        .background(.ultraThinMaterial, in: .capsule)
        .padding(.top, 4)
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
