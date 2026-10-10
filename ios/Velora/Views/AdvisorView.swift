import SwiftUI
import VeloraKit

/// Empfehlungen und Briefings des KI-Beraters.
struct AdvisorView: View {
    @Environment(AppModel.self) private var model
    @State private var path = NavigationPath()

    var body: some View {
        @Bindable var model = model
        NavigationStack(path: $path) {
            Group {
                switch model.advisorSection {
                case .recommendations: RecommendationsList()
                case .briefings: BriefingsList()
                }
            }
            .safeAreaInset(edge: .top) {
                Picker("Bereich", selection: $model.advisorSection) {
                    ForEach(AdvisorSection.allCases) { section in
                        if section == .recommendations, model.actionableCount > 0 {
                            Text("\(section.rawValue) (\(model.actionableCount))").tag(section)
                        } else {
                            Text(section.rawValue).tag(section)
                        }
                    }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal)
                .padding(.bottom, 6)
            }
            .navigationTitle("Berater")
            .navigationDestination(for: Briefing.self) { BriefingDetailView(briefing: $0) }
            .navigationDestination(for: Recommendation.self) { RecommendationDetailView(recommendation: $0) }
        }
        // Sprung von anderswo (Dashboard, Briefing) landet in der Liste, nicht in einer alten Detailseite.
        .onChange(of: model.selectedTab) { _, tab in
            if tab == .advisor, !path.isEmpty { path = NavigationPath() }
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
            let pending = data.recommendations.filter { $0.status == "order_placed" }
            let closed = data.recommendations.filter { !$0.isOpen && $0.status != "order_placed" }
            List {
                Section {
                    if actionable.isEmpty {
                        Label {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Gerade nichts zu tun").font(.subheadline.weight(.medium))
                                Text("Neue Empfehlungen kommen mit dem nächsten Briefing.")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        } icon: {
                            Image(systemName: "checkmark.seal").foregroundStyle(Theme.accent)
                        }
                    }
                    ForEach(actionable) { rec in
                        NavigationLink(value: rec) { RecommendationRow(recommendation: rec, eurUsd: data.eurUsd) }
                    }
                } header: {
                    Text(actionable.isEmpty ? "Umsetzen" : "Umsetzen · \(actionable.count)")
                }

                if !data.openOrders.isEmpty || !pending.isEmpty {
                    Section("Order beim Broker platziert") {
                        ForEach(data.openOrders) { OrderRow(order: $0, eurUsd: data.eurUsd) }
                    }
                }
                if !watch.isEmpty {
                    Section("Watchlist") {
                        ForEach(watch) { rec in
                            NavigationLink(value: rec) { RecommendationRow(recommendation: rec, eurUsd: data.eurUsd) }
                        }
                    }
                }
                if !closed.isEmpty {
                    Section("Abgeschlossen") {
                        ForEach(closed.prefix(30)) { rec in
                            NavigationLink(value: rec) { ClosedRecommendationRow(recommendation: rec) }
                        }
                    }
                }
            }
        }
    }
}

/// Eine offene Empfehlung: was, welcher Titel, welcher Kurs – auf einen Blick.
struct RecommendationRow: View {
    var recommendation: Recommendation
    var eurUsd: Double?

    var body: some View {
        let rec = recommendation
        HStack(alignment: .top, spacing: 12) {
            IconBadge(systemImage: Theme.actionIcon(rec), color: Theme.action(rec.action))
            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(rec.actionLabel)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(Theme.action(rec.action))
                        Text(rec.displayName).font(.headline).lineLimit(1)
                    }
                    Spacer(minLength: 8)
                    if let price = rec.keyPrice {
                        PriceStack(value: price, currency: rec.currency, eurUsd: eurUsd)
                    }
                }
                detailLine
                if !rec.reasoning.isEmpty {
                    Text(rec.reasoning).font(.footnote).foregroundStyle(.secondary).lineLimit(2)
                }
            }
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder private var detailLine: some View {
        let rec = recommendation
        HStack(spacing: 10) {
            if rec.isStopAction {
                if let current = rec.currentStopBroker {
                    Text("bisher \(Format.price(current, currency: rec.currentStopCurrency ?? rec.currency))")
                    if let raise = rec.stopRaisePct { Text(Format.pct(raise)).foregroundStyle(Theme.accent) }
                } else {
                    Text("noch kein Stop gesetzt").foregroundStyle(Theme.amber)
                }
            } else {
                if let target = rec.targetPrice { Text("Ziel \(Format.price(target, currency: rec.currency))") }
                if let stop = rec.stopLoss { Text("Stop \(Format.price(stop, currency: rec.currency))") }
            }
            Spacer(minLength: 0)
            Text(Format.date(rec.date)).foregroundStyle(.tertiary)
        }
        .font(.caption).foregroundStyle(.secondary).monospacedDigit()
        .lineLimit(1)
    }
}

private struct ClosedRecommendationRow: View {
    var recommendation: Recommendation

    var body: some View {
        let rec = recommendation
        HStack(spacing: 10) {
            Image(systemName: Theme.actionIcon(rec)).foregroundStyle(.secondary).frame(width: 20)
            VStack(alignment: .leading, spacing: 2) {
                Text("\(rec.actionLabel) · \(rec.displayName)").font(.subheadline).lineLimit(1)
                Text(Format.date(rec.date)).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Text(rec.statusLabel).font(.caption).foregroundStyle(.secondary)
        }
    }
}

// MARK: - Detail

struct RecommendationDetailView: View {
    var recommendation: Recommendation

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var accounts: [String] = []
    @State private var showOrder = false
    @State private var showTrade = false
    @State private var stopTarget: StopTarget?
    @State private var error: String?

    var body: some View {
        let rec = recommendation
        let eurUsd = model.eurUsd
        List {
            Section {
                VStack(alignment: .leading, spacing: 14) {
                    HStack(spacing: 12) {
                        IconBadge(systemImage: Theme.actionIcon(rec), color: Theme.action(rec.action), size: 48)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(rec.actionLabel).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.action(rec.action))
                            Text(rec.displayName).font(.title2.weight(.bold)).lineLimit(2)
                            Text([rec.ticker, rec.account.map(Format.accountName)].compactMap { $0 }.joined(separator: " · "))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    if let price = rec.keyPrice {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(rec.isStopAction ? "Neuer Stop" : rec.action == "watch" ? "Einstieg ab" : "Limit")
                                .font(.caption).foregroundStyle(.secondary)
                            PriceStack(value: price, currency: rec.currency, eurUsd: eurUsd, alignment: .leading,
                                       font: .system(size: 30, weight: .bold, design: .rounded))
                        }
                    }
                    HStack(spacing: 6) {
                        Pill(text: rec.statusLabel, color: rec.isOpen ? Theme.accent : .secondary)
                        Text("vom \(Format.date(rec.date))").font(.caption).foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 6)
            }

            if rec.isOpen, let instruction {
                Section("So setzt du es um") {
                    Label { Text(instruction).font(.subheadline) } icon: {
                        Image(systemName: "list.number").foregroundStyle(Theme.accent)
                    }
                }
            }

            Section("Begründung") {
                Text(rec.reasoning).font(.callout).lineSpacing(2)
            }

            Section("Kursmarken") {
                if rec.isStopAction, rec.currentStopBroker != nil || rec.currentStop != nil {
                    LabeledContent("Stop bisher") {
                        PriceStack(value: rec.currentStopBroker, currency: rec.currentStopCurrency ?? rec.currency,
                                   eurUsd: eurUsd, font: .body)
                    }
                }
                if let price = rec.currentPrice {
                    LabeledContent("Aktueller Kurs") { PriceStack(value: price, currency: rec.currency, eurUsd: eurUsd, font: .body) }
                }
                if !rec.isStopAction, let entry = rec.entryPrice {
                    LabeledContent("Einstieg") { PriceStack(value: entry, currency: rec.currency, eurUsd: eurUsd, font: .body) }
                }
                if let target = rec.targetPrice {
                    LabeledContent("Ziel") { PriceStack(value: target, currency: rec.currency, eurUsd: eurUsd, font: .body) }
                }
                if let stop = rec.stopLoss {
                    LabeledContent(rec.isStopAction ? "Stop neu" : "Stop-Loss") {
                        PriceStack(value: stop, currency: rec.currency, eurUsd: eurUsd, font: .body)
                    }
                }
                if let held = rec.sharesHeld {
                    LabeledContent("Im Depot", value: "\(Format.shares(held)) Stk.")
                }
                if let outcome = rec.outcome, !outcome.isEmpty { LabeledContent("Ergebnis", value: outcome) }
            }

            if rec.isOpen {
                Section {
                    if rec.isStopAction {
                        Button {
                            stopTarget = StopTarget(recommendation: rec)
                        } label: {
                            Label("Stop beim Broker eingetragen", systemImage: "checkmark.shield")
                                .font(.body.weight(.semibold))
                        }
                        .disabled(rec.account == nil)
                    }
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
                } footer: {
                    if rec.isStopAction {
                        Text("Speichert den Stop an der Position (in € oder $, wie beim Broker) und schliesst die Empfehlung.")
                    }
                }
            }
        }
        .navigationTitle(rec.ticker)
        .navigationBarTitleDisplayMode(.inline)
        .task { accounts = (try? await model.client.get("/api/accounts", as: [String].self)) ?? [] }
        .sheet(isPresented: $showOrder) {
            OrderSheet(ticker: rec.ticker, action: rec.action == "sell" ? "sell" : "buy", currency: rec.currency,
                       accounts: accounts, recTicker: rec.ticker, presetAccount: rec.account,
                       presetShares: rec.shares, presetLimit: rec.entryPrice)
        }
        .sheet(isPresented: $showTrade) { TradeSheet(position: nil, accounts: accounts, presetTicker: rec.ticker, presetCurrency: rec.currency) }
        .sheet(item: $stopTarget) { target in
            EditStopSheet(target: target) {
                // Empfehlung ist damit erledigt – zurück zur Liste, sobald das Formular zu ist.
                Task {
                    try? await Task.sleep(for: .milliseconds(450))
                    dismiss()
                }
            }
        }
        .errorAlert($error)
    }

    /// Ein Satz, was beim Broker konkret zu tun ist.
    private var instruction: String? {
        let rec = recommendation
        let broker = rec.account.map(Format.accountName) ?? "deinem Broker"
        func both(_ v: Double?) -> String {
            guard let v else { return "–" }
            let main = Format.price(v, currency: rec.currency)
            return Format.eurHint(v, currency: rec.currency, eurUsd: model.eurUsd).map { "\(main) (\($0))" } ?? main
        }
        switch rec.action {
        case "hold" where rec.stopLoss != nil:
            if rec.currentStopBroker != nil {
                return "Bei \(broker) die Stop-Order für \(rec.displayName) von \(Format.price(rec.currentStopBroker, currency: rec.currentStopCurrency ?? rec.currency)) auf \(both(rec.stopLoss)) ändern."
            }
            return "Bei \(broker) eine Stop-Order (Verkauf) für \(rec.displayName) bei \(both(rec.stopLoss)) anlegen."
        case "buy":
            let qty = rec.shares.map { "\(Format.shares($0)) Stk. " } ?? ""
            return "Limit-Kauf \(qty)\(rec.displayName) zu \(both(rec.entryPrice)) aufgeben – danach hier als Order eintragen."
        case "sell":
            return "Verkauf von \(rec.displayName)\(rec.entryPrice.map { " mit Limit \(both($0))" } ?? "") aufgeben."
        case "watch" where rec.entryPrice != nil:
            return "Kaufen, wenn \(rec.displayName) auf \(both(rec.entryPrice)) fällt – am besten gleich als Limit-Order."
        default:
            return nil
        }
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
