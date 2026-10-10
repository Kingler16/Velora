import SwiftUI
import VeloraKit

// MARK: - Liste

struct BriefingsList: View {
    var body: some View {
        RemoteView(path: "/api/app/briefings") { (data: BriefingsData) in
            List {
                if let latest = data.briefings.first {
                    Section {
                        NavigationLink(value: latest) { LatestBriefingRow(briefing: latest) }
                    } header: {
                        Text("Neuestes Briefing")
                    }
                } else {
                    ContentUnavailableView("Noch keine Briefings", systemImage: "doc.text",
                                           description: Text("Velora schreibt sie zu den eingestellten Zeiten."))
                }

                if let notes = data.notes, !notes.keyInsights.isEmpty {
                    Section {
                        DisclosureGroup {
                            ForEach(Array(notes.keyInsights.suffix(6).reversed().enumerated()), id: \.offset) { _, insight in
                                Label { Text(insight).font(.subheadline) } icon: {
                                    Image(systemName: "lightbulb").foregroundStyle(Theme.amber)
                                }
                            }
                        } label: {
                            Label("Erkenntnisse aus den letzten Briefings", systemImage: "lightbulb")
                                .font(.subheadline.weight(.medium))
                        }
                    }
                }

                if data.briefings.count > 1 {
                    Section("Frühere") {
                        ForEach(data.briefings.dropFirst()) { briefing in
                            NavigationLink(value: briefing) { BriefingRow(briefing: briefing) }
                        }
                    }
                }
            }
        }
    }
}

private struct LatestBriefingRow: View {
    var briefing: Briefing

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text(Format.date(briefing.date, time: true)).font(.headline)
                Spacer()
                Text(Format.relative(briefing.date)).font(.caption).foregroundStyle(.secondary)
            }
            Text(briefing.summary).font(.subheadline).lineSpacing(2)
            BriefingBadges(briefing: briefing)
        }
        .padding(.vertical, 6)
    }
}

private struct BriefingRow: View {
    var briefing: Briefing

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(Format.date(briefing.date)).font(.subheadline.weight(.semibold))
                Spacer()
                if briefing.recommendationCount > 0 {
                    Label("\(briefing.recommendationCount)", systemImage: "checklist")
                        .font(.caption.weight(.medium)).foregroundStyle(Theme.violet)
                        .labelStyle(.titleAndIcon)
                }
            }
            Text(briefing.summary).font(.footnote).foregroundStyle(.secondary).lineLimit(2)
        }
        .padding(.vertical, 2)
    }
}

private struct BriefingBadges: View {
    var briefing: Briefing

    var body: some View {
        HStack(spacing: 6) {
            if briefing.recommendationCount > 0 {
                Pill(text: briefing.recommendationCount == 1 ? "1 Empfehlung" : "\(briefing.recommendationCount) Empfehlungen",
                     color: Theme.violet)
            }
            if briefing.hadActions { Pill(text: "Handlungsbedarf", color: Theme.amber) }
        }
    }
}

// MARK: - Detail

struct BriefingDetailView: View {
    var briefing: Briefing

    @Environment(AppModel.self) private var model
    @State private var expanded: Set<String> = []
    @State private var document: BriefingDocument?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header
                if let document {
                    ForEach(document.sections) { section in
                        BriefingSectionCard(
                            section: section,
                            expanded: Binding(
                                get: { expanded.contains(section.id) },
                                set: { if $0 { expanded.insert(section.id) } else { expanded.remove(section.id) } }
                            ),
                            openRecommendations: openRecommendations
                        )
                    }
                }
            }
            .padding()
        }
        .navigationTitle(Format.date(briefing.date))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if let document, document.sections.count > 1 {
                ToolbarItem(placement: .topBarTrailing) {
                    let allOpen = expanded.count == document.sections.count
                    Button {
                        withAnimation(.snappy) { expanded = allOpen ? [] : Set(document.sections.map(\.id)) }
                    } label: {
                        Image(systemName: allOpen ? "rectangle.compress.vertical" : "rectangle.expand.vertical")
                    }
                    .accessibilityLabel(allOpen ? "Alle zuklappen" : "Alle aufklappen")
                }
            }
            if let text = briefing.fullText, briefing.hasFullText {
                ToolbarItem(placement: .topBarTrailing) {
                    ShareLink(item: InlineRun.plain(text), subject: Text("Velora-Briefing \(Format.date(briefing.date))"))
                }
            }
        }
        .task(id: briefing.id) {
            guard document == nil, let text = briefing.fullText, briefing.hasFullText else { return }
            let doc = BriefingDocument.parse(text)
            document = doc
            // Was man sofort braucht, ist offen; der Rest wartet eingeklappt mit Vorschau.
            expanded = Set(doc.sections.filter { [.recommendations, .market, .stops].contains($0.kind) || doc.sections.count <= 2 }.map(\.id))
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(Format.date(briefing.date, time: true))
                    .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    .textCase(.uppercase)
                Text("Kurzfassung").font(.title2.weight(.bold))
            }
            Text(briefing.summary).font(.body).lineSpacing(3)
            if let regime = briefing.marketRegime, !regime.isEmpty {
                Label { Text(regime).font(.subheadline).foregroundStyle(.secondary) } icon: {
                    Image(systemName: "gauge.with.dots.needle.50percent").foregroundStyle(Theme.accent)
                }
            }
            HStack {
                BriefingBadges(briefing: briefing)
                Spacer()
                if briefing.recommendationCount > 0 {
                    Button("Empfehlungen", systemImage: "arrow.right", action: openRecommendations)
                        .labelStyle(.titleAndIcon)
                        .font(.subheadline.weight(.medium))
                        .buttonStyle(.borderless)
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            LinearGradient(colors: [Theme.accent.opacity(0.16), Theme.indigo.opacity(0.08), .clear],
                           startPoint: .topLeading, endPoint: .bottomTrailing),
            in: .rect(cornerRadius: 22)
        )
        .background(.background.secondary, in: .rect(cornerRadius: 22))
    }

    private func openRecommendations() {
        model.advisorSection = .recommendations
        model.selectedTab = .advisor
    }
}

private struct BriefingSectionCard: View {
    var section: BriefingSection
    @Binding var expanded: Bool
    var openRecommendations: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Button {
                withAnimation(.snappy) { expanded.toggle() }
            } label: {
                HStack(spacing: 12) {
                    IconBadge(systemImage: style.icon, color: style.color, size: 32)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(section.displayTitle).font(.headline)
                        if let subtitle = section.subtitle {
                            Text(subtitle).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                    Spacer()
                    Image(systemName: "chevron.down")
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(.tertiary)
                        .rotationEffect(.degrees(expanded ? 0 : -90))
                }
                .contentShape(.rect)
            }
            .buttonStyle(.plain)

            if expanded {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(Array(section.blocks.enumerated()), id: \.offset) { _, block in
                        BriefingBlockView(block: block, accent: style.color)
                    }
                    if section.kind == .recommendations {
                        Button("Zu den Empfehlungen", systemImage: "checklist", action: openRecommendations)
                            .buttonStyle(.bordered)
                            .tint(Theme.violet)
                            .padding(.top, 2)
                    }
                }
                .transition(.opacity)
            } else if !section.preview.isEmpty {
                Text(section.preview)
                    .font(.footnote).foregroundStyle(.secondary).lineLimit(2)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.background.secondary, in: .rect(cornerRadius: 20))
    }

    private var style: (icon: String, color: Color) {
        switch section.kind {
        case .market: ("globe.europe.africa.fill", Theme.accent)
        case .portfolio: ("briefcase.fill", Theme.cyan)
        case .stops: ("shield.lefthalf.filled", Theme.amber)
        case .events: ("calendar", Theme.indigo)
        case .recommendations: ("checklist", Theme.violet)
        case .ideas: ("sparkles", Theme.cyan)
        case .risks: ("exclamationmark.triangle.fill", Theme.loss)
        case .track: ("chart.bar.xaxis", Theme.indigo)
        case .other: ("doc.text", Color.secondary)
        }
    }
}

private struct BriefingBlockView: View {
    var block: BriefingBlock
    var accent: Color

    var body: some View {
        switch block {
        case .paragraph(let runs):
            RichText(runs: runs)
        case .bullet(let runs):
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Circle().fill(accent.opacity(0.8)).frame(width: 5, height: 5)
                    .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 4 }
                RichText(runs: runs)
            }
        case .numbered(let number, let runs):
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(number)
                    .font(.caption.weight(.bold)).monospacedDigit()
                    .foregroundStyle(accent)
                    .frame(width: 20, height: 20)
                    .background(accent.opacity(0.15), in: .circle)
                    .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 5 }
                RichText(runs: runs)
            }
        }
    }
}

/// Textstücke mit Auszeichnung als ein Fliesstext.
struct RichText: View {
    var runs: [InlineRun]

    var body: some View {
        Text(attributed)
            .font(.callout)
            .lineSpacing(3)
            .frame(maxWidth: .infinity, alignment: .leading)
            .textSelection(.enabled)
    }

    private var attributed: AttributedString {
        var result = AttributedString()
        for run in runs {
            if run.tag {
                // „[Fakt]“ und „[Einschätzung]“ dezent, damit sie den Lesefluss nicht stören.
                var tag = AttributedString(run.text.uppercased())
                tag.font = .caption2.weight(.semibold)
                tag.foregroundColor = .secondary
                result += tag
                continue
            }
            var piece = AttributedString(run.text)
            if run.code {
                piece.font = .callout.monospacedDigit().weight(.semibold)
                piece.foregroundColor = Theme.cyan
            } else if run.bold && run.italic {
                piece.font = .callout.weight(.semibold).italic()
            } else if run.bold {
                piece.font = .callout.weight(.semibold)
            } else if run.italic {
                piece.font = .callout.italic()
            }
            result += piece
        }
        return result
    }
}
