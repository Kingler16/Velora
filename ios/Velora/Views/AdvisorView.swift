import SwiftUI
import VeloraKit

/// Briefings und Empfehlungen des KI-Beraters.
struct AdvisorView: View {
    enum Section: String, CaseIterable, Identifiable {
        case briefings = "Briefings", recommendations = "Empfehlungen"
        var id: Self { self }
    }

    @State private var section = Section.briefings

    var body: some View {
        NavigationStack {
            Group {
                switch section {
                case .briefings: BriefingsList()
                case .recommendations: RecommendationsList()
                }
            }
            .safeAreaInset(edge: .top) {
                Picker("Bereich", selection: $section) {
                    ForEach(Section.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal)
                .padding(.bottom, 6)
            }
            .navigationTitle("Berater")
            .navigationDestination(for: Briefing.self) { BriefingDetailView(briefing: $0) }
            .navigationDestination(for: Recommendation.self) { RecommendationDetailView(recommendation: $0) }
        }
    }
}

// MARK: - Briefings

private struct BriefingsList: View {
    var body: some View {
        RemoteView(path: "/api/app/briefings") { (data: BriefingsData) in
            List {
                if let notes = data.notes {
                    if let regime = notes.marketRegime, !regime.isEmpty {
                        Section("Marktlage") {
                            Text(regime).font(.subheadline)
                        }
                    }
                    if !notes.keyInsights.isEmpty {
                        Section("Erkenntnisse") {
                            ForEach(Array(notes.keyInsights.suffix(6).reversed().enumerated()), id: \.offset) { _, insight in
                                Label { Text(insight).font(.subheadline) } icon: {
                                    Image(systemName: "lightbulb").foregroundStyle(Theme.amber)
                                }
                            }
                        }
                    }
                }
                Section("Verlauf") {
                    if data.briefings.isEmpty {
                        Text("Noch keine Briefings.").foregroundStyle(.secondary)
                    }
                    ForEach(data.briefings) { briefing in
                        NavigationLink(value: briefing) {
                            VStack(alignment: .leading, spacing: 6) {
                                HStack {
                                    Text(Format.date(briefing.date, time: true)).font(.subheadline.weight(.semibold))
                                    Spacer()
                                    if briefing.hadActions { Pill(text: "Aktion", color: Theme.amber) }
                                }
                                Text(briefing.summary).font(.subheadline).foregroundStyle(.secondary).lineLimit(4)
                            }
                            .padding(.vertical, 2)
                        }
                    }
                }
            }
        }
    }
}

struct BriefingDetailView: View {
    var briefing: Briefing

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    if briefing.recommendationCount > 0 {
                        Pill(text: "\(briefing.recommendationCount) Empfehlungen", color: Theme.cyan)
                    }
                    if briefing.hadActions { Pill(text: "Handlungsbedarf", color: Theme.amber) }
                }
                if let regime = briefing.marketRegime, !regime.isEmpty {
                    Card(title: "Marktlage") { Text(regime).font(.subheadline) }
                }
                Card(title: "Zusammenfassung") { Text(briefing.summary).font(.subheadline) }
                if let text = briefing.fullText, briefing.hasFullText {
                    MarkdownText(text: text)
                        .font(.callout)
                        .padding(.top, 4)
                }
            }
            .padding()
        }
        .navigationTitle(Format.date(briefing.date))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if let text = briefing.fullText, briefing.hasFullText {
                ShareLink(item: text, subject: Text("Velora-Briefing \(Format.date(briefing.date))"))
            }
        }
    }
}

// MARK: - Empfehlungen

private struct RecommendationsList: View {
    var body: some View {
        RemoteView(path: "/api/app/recommendations") { (data: RecommendationsData) in
            let open = data.recommendations.filter(\.isOpen)
            let actionable = open.filter(\.isActionable)
            let watch = open.filter { !$0.isActionable }
            let closed = data.recommendations.filter { !$0.isOpen }
            List {
                Section {
                    if actionable.isEmpty { Text("Nichts zu tun.").foregroundStyle(.secondary) }
                    ForEach(actionable) { rec in
                        NavigationLink(value: rec) { RecommendationRow(recommendation: rec) }
                    }
                } header: {
                    Text("Umsetzen")
                } footer: {
                    Text("Kaufen/Verkaufen, Beobachten mit Einstiegskurs, Halten mit Stop zum Nachziehen.")
                }
                if !data.openOrders.isEmpty {
                    Section("Platzierte Orders") {
                        ForEach(data.openOrders) { OrderRow(order: $0) }
                    }
                }
                if !watch.isEmpty {
                    Section("Watchlist") {
                        ForEach(watch) { rec in
                            NavigationLink(value: rec) { RecommendationRow(recommendation: rec) }
                        }
                    }
                }
                if !closed.isEmpty {
                    Section("Abgeschlossen") {
                        ForEach(closed.prefix(30)) { rec in
                            NavigationLink(value: rec) { RecommendationRow(recommendation: rec) }
                        }
                    }
                }
            }
        }
    }
}

struct RecommendationRow: View {
    var recommendation: Recommendation

    var body: some View {
        let rec = recommendation
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Pill(text: rec.actionLabel, color: Theme.action(rec.action))
                Text(rec.ticker).font(.subheadline.weight(.semibold))
                Spacer()
                if !rec.isOpen {
                    Text(rec.statusLabel).font(.caption).foregroundStyle(.secondary)
                } else if let entry = rec.entryPrice {
                    Text(Format.price(entry, currency: rec.currency)).font(.subheadline).monospacedDigit()
                }
            }
            Text(rec.reasoning).font(.caption).foregroundStyle(.secondary).lineLimit(2)
            HStack(spacing: 12) {
                if let target = rec.targetPrice { Text("Ziel \(Format.price(target, currency: rec.currency))") }
                if let stop = rec.stopLoss { Text("Stop \(Format.price(stop, currency: rec.currency))") }
                Spacer()
                Text(Format.date(rec.date))
            }
            .font(.caption2).foregroundStyle(.tertiary).monospacedDigit()
        }
        .padding(.vertical, 2)
    }
}

struct RecommendationDetailView: View {
    var recommendation: Recommendation

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var accounts: [String] = []
    @State private var showOrder = false
    @State private var showTrade = false
    @State private var error: String?

    var body: some View {
        let rec = recommendation
        List {
            Section {
                HStack {
                    Pill(text: rec.actionLabel, color: Theme.action(rec.action))
                    Pill(text: rec.statusLabel, color: rec.isOpen ? Theme.cyan : .secondary)
                    Spacer()
                    Text(Format.date(rec.date)).font(.caption).foregroundStyle(.secondary)
                }
                Text(rec.reasoning).font(.body)
            }
            Section("Kursmarken") {
                LabeledContent("Einstieg", value: Format.price(rec.entryPrice, currency: rec.currency))
                LabeledContent("Ziel", value: Format.price(rec.targetPrice, currency: rec.currency))
                LabeledContent("Stop-Loss", value: Format.price(rec.stopLoss, currency: rec.currency))
                if let outcome = rec.outcome, !outcome.isEmpty { LabeledContent("Ergebnis", value: outcome) }
            }
            .monospacedDigit()

            if rec.isOpen {
                Section {
                    if rec.action == "buy" || rec.action == "sell" || rec.action == "watch" {
                        Button("Limit-Order platzieren", systemImage: "list.bullet.clipboard") { showOrder = true }
                        Button("Ausgeführten Trade erfassen", systemImage: "arrow.left.arrow.right") { showTrade = true }
                    }
                    Menu {
                        Button("Ausgeführt") { close("executed") }
                        Button("Ziel erreicht") { close("target_hit") }
                        Button("Stop ausgelöst") { close("stop_hit") }
                        Button("Verwerfen", role: .destructive) { close("cancelled") }
                    } label: {
                        Label("Als erledigt markieren", systemImage: "checkmark.circle")
                    }
                }
            }
        }
        .navigationTitle(rec.ticker)
        .navigationBarTitleDisplayMode(.inline)
        .task { accounts = (try? await model.client.get("/api/accounts", as: [String].self)) ?? [] }
        .sheet(isPresented: $showOrder) {
            OrderSheet(ticker: rec.ticker, action: rec.action == "sell" ? "sell" : "buy", currency: rec.currency,
                       accounts: accounts, recTicker: rec.ticker)
        }
        .sheet(isPresented: $showTrade) { TradeSheet(position: nil, accounts: accounts, presetTicker: rec.ticker, presetCurrency: rec.currency) }
        .errorAlert($error)
    }

    private func close(_ status: String) {
        Task {
            do {
                try await model.send("/api/recommendations/close", ["ticker": .string(recommendation.ticker), "status": .string(status)])
                dismiss()
            } catch { self.error = error.localizedDescription }
        }
    }
}
