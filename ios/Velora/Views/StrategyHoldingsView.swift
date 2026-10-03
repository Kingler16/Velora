import SwiftUI
import VeloraKit

/// Anlagemandat und Abweichung des Depots davon.
struct StrategyView: View {
    var body: some View {
        RemoteView(path: "/api/app/strategy") { (data: StrategyData) in
            if let mandate = data.mandate {
                List {
                    if let drift = data.drift {
                        Section {
                            HStack {
                                StatusBadge(status: drift.status)
                                Spacer()
                                Text("\(drift.breaches) Verstöße · \(drift.warnings) Warnungen")
                                    .font(.subheadline).foregroundStyle(.secondary)
                            }
                            ForEach(drift.dimensions) { d in
                                VStack(alignment: .leading, spacing: 6) {
                                    HStack {
                                        Text(d.name).font(.subheadline).lineLimit(1)
                                        Spacer()
                                        Text("Ist \(Format.pct(d.actual, signed: false)) · Soll \(Format.pct(d.target, digits: 0, signed: false))")
                                            .font(.caption).monospacedDigit().foregroundStyle(.secondary)
                                    }
                                    DriftBar(target: d.target ?? 0, actual: d.actual ?? 0, color: Theme.severity(d.severity))
                                }
                            }
                        } header: {
                            Text("Abweichung vom Mandat")
                        }
                    }
                    Section("Ziel") {
                        Text(mandate.summary).font(.subheadline)
                        if let years = mandate.horizonYears { LabeledContent("Horizont", value: "\(years) Jahre") }
                        if let monthly = mandate.monthlyContributionEur { LabeledContent("Sparrate", value: Format.eur(monthly, digits: 0) + " / Monat") }
                        if let cap = mandate.singleTradeCapPct { LabeledContent("Max. je Trade", value: Format.pct(cap, digits: 0, signed: false)) }
                    }
                    if !mandate.philosophy.isEmpty {
                        Section("Philosophie") { Text(mandate.philosophy).font(.subheadline) }
                    }
                    Section("Harte Regeln") {
                        ForEach(mandate.hardRules) { rule in
                            Label {
                                Text(rule.label).font(.subheadline)
                            } icon: {
                                Image(systemName: rule.rule == "block" ? "nosign" : "exclamationmark.triangle")
                                    .foregroundStyle(Theme.severity(rule.rule))
                            }
                        }
                    }
                    if !mandate.softPreferences.isEmpty {
                        Section("Vorlieben") {
                            ForEach(mandate.softPreferences, id: \.self) { Text($0).font(.subheadline) }
                        }
                    }
                    if !mandate.taxDirectives.isEmpty {
                        Section("Steuer") {
                            ForEach(mandate.taxDirectives, id: \.self) { Text($0).font(.subheadline) }
                        }
                    }
                    if let updated = mandate.updatedAt {
                        Section {
                            Text("Version \(mandate.version ?? 1) · geändert \(Format.date(updated))")
                                .font(.footnote).foregroundStyle(.secondary)
                        } footer: {
                            Text("Das Mandat änderst du am einfachsten im Chat („Ändere mein Mandat …“).")
                        }
                    }
                }
            } else {
                ContentUnavailableView("Kein Mandat", systemImage: "scope",
                                       description: Text("Leg im Chat fest, wie Velora dein Depot steuern soll."))
            }
        }
        .navigationTitle("Strategie")
    }
}

private struct StatusBadge: View {
    var status: String

    var body: some View {
        switch status {
        case "breach": Label("Verstoß", systemImage: "xmark.octagon.fill").foregroundStyle(Theme.loss)
        case "warn": Label("Warnung", systemImage: "exclamationmark.triangle.fill").foregroundStyle(Theme.amber)
        default: Label("Im Rahmen", systemImage: "checkmark.seal.fill").foregroundStyle(Theme.gain)
        }
    }
}

/// Ist-Balken mit Markierung für den Sollwert.
private struct DriftBar: View {
    var target: Double
    var actual: Double
    var color: Color

    var body: some View {
        GeometryReader { geo in
            let scale = max(target, actual, 1) * 1.15
            ZStack(alignment: .leading) {
                Capsule().fill(.quaternary)
                Capsule().fill(color).frame(width: geo.size.width * actual / scale)
                Rectangle().fill(.primary).frame(width: 2, height: 12)
                    .offset(x: geo.size.width * target / scale - 1)
            }
        }
        .frame(height: 8)
        .accessibilityLabel("Ist \(Format.pct(actual, signed: false)), Soll \(Format.pct(target, signed: false))")
    }
}

/// Durchschau: was in den Fonds und ETFs tatsächlich steckt.
struct HoldingsView: View {
    @Environment(AppModel.self) private var model
    @State private var error: String?

    var body: some View {
        RemoteView(path: "/api/app/holdings") { (data: HoldingsData) in
            List {
                if let lt = data.lookthrough {
                    WeightSection(title: "Regionen (durchgerechnet)", items: lt.regions)
                    WeightSection(title: "Sektoren (durchgerechnet)", items: lt.sectors)
                    WeightSection(title: "Größte Einzeltitel", items: Array(lt.topTitles.prefix(12)))
                    if !lt.assetClass.isEmpty { WeightSection(title: "Anlageklassen", items: lt.assetClass) }
                }
                Section {
                    ForEach(data.funds) { fund in
                        NavigationLink { FundDetailView(fund: fund) } label: {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(fund.name).font(.subheadline.weight(.medium)).lineLimit(2)
                                HStack(spacing: 6) {
                                    Text(fund.ticker)
                                    if let ter = fund.research?.terPct { Text("TER \(Format.pct(ter, digits: 2, signed: false))") }
                                    if fund.research == nil { Text("noch nicht recherchiert").foregroundStyle(Theme.amber) }
                                }
                                .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                } header: {
                    Text("Fonds & ETFs")
                } footer: {
                    if data.researchRunning {
                        Label("Recherche läuft am Server …", systemImage: "hourglass")
                    }
                }
            }
            .toolbar {
                Button("Recherchieren", systemImage: "sparkle.magnifyingglass") {
                    Task {
                        do { try await model.send("/api/holdings/research") } catch { self.error = error.localizedDescription }
                    }
                }
                .disabled(data.researchRunning)
            }
        }
        .navigationTitle("Durchschau")
        .errorAlert($error)
    }
}

private struct WeightSection: View {
    var title: String
    var items: [WeightedItem]

    var body: some View {
        if !items.isEmpty {
            Section(title) {
                let maxPct = items.map(\.pct).max() ?? 100
                ForEach(Array(items.enumerated()), id: \.offset) { i, item in
                    ShareBar(label: item.name, pct: item.pct, detail: item.valueEur.map { Format.eur($0, digits: 0) },
                             color: Theme.series[i % Theme.series.count], maxPct: maxPct)
                }
            }
        }
    }
}

private struct FundDetailView: View {
    var fund: Fund

    var body: some View {
        List {
            if let r = fund.research {
                if let summary = r.summary { Section { Text(summary).font(.subheadline) } }
                Section("Eckdaten") {
                    LabeledContent("ISIN", value: fund.isin)
                    if let type = r.instrumentType { LabeledContent("Art", value: type.uppercased()) }
                    if let ter = r.terPct { LabeledContent("Laufende Kosten", value: Format.pct(ter, digits: 2, signed: false)) }
                    if let shares = fund.shares { LabeledContent("Stück", value: Format.shares(shares)) }
                    if let confidence = r.confidence { LabeledContent("Datenqualität", value: confidence) }
                }
                if !r.topHoldings.isEmpty {
                    Section("Top-Positionen") {
                        let maxPct = r.topHoldings.map(\.pct).max() ?? 10
                        ForEach(r.topHoldings) { ShareBar(label: $0.name, pct: $0.pct, maxPct: maxPct) }
                    }
                }
                if !r.regionBreakdown.isEmpty {
                    Section("Regionen") {
                        ForEach(r.regionBreakdown.sorted { $0.value > $1.value }, id: \.key) {
                            ShareBar(label: $0.key, pct: $0.value, color: Theme.cyan)
                        }
                    }
                }
                if !r.sectorBreakdown.isEmpty {
                    Section("Sektoren") {
                        let maxPct = r.sectorBreakdown.values.max() ?? 100
                        ForEach(r.sectorBreakdown.sorted { $0.value > $1.value }, id: \.key) {
                            ShareBar(label: $0.key, pct: $0.value, color: Theme.violet, maxPct: maxPct)
                        }
                    }
                }
                if let source = r.source {
                    Section {
                        Text("Quelle: \(source)").font(.footnote).foregroundStyle(.secondary)
                        if let at = r.researchedAt { Text("Recherchiert \(Format.date(at))").font(.footnote).foregroundStyle(.secondary) }
                    }
                }
            } else {
                ContentUnavailableView("Noch nicht recherchiert", systemImage: "magnifyingglass",
                                       description: Text("Über „Recherchieren“ lässt Velora die Zusammensetzung ermitteln."))
            }
        }
        .navigationTitle(fund.ticker.isEmpty ? fund.name : fund.ticker)
        .navigationBarTitleDisplayMode(.inline)
    }
}
