import SwiftUI
import VeloraKit

struct PositionDetailView: View {
    var position: Position
    var stop: StopPosition?
    var stopLabel: String?
    var accounts: [String]

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var sheet: PortfolioSheet?
    @State private var confirmDelete = false
    @State private var error: String?

    var body: some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 6) {
                    Text(Format.eur(position.currentValueEur))
                        .font(.system(size: 32, weight: .bold, design: .rounded)).monospacedDigit()
                    HStack(spacing: 12) {
                        ChangeLabel(pct: position.changePct)
                        Text("heute").font(.subheadline).foregroundStyle(.secondary)
                    }
                    HStack(spacing: 6) {
                        Text("Gesamt").font(.subheadline).foregroundStyle(.secondary)
                        ChangeLabel(pct: position.pnlPct, eur: position.pnlEur)
                    }
                }
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets())
            }

            Section("Bestand") {
                LabeledContent("Stück", value: Format.shares(position.shares))
                LabeledContent("Kaufkurs", value: Format.price(position.buyIn, currency: position.currency))
                if position.currency != "EUR", let eur = position.buyInEur {
                    LabeledContent("Kaufkurs in EUR", value: Format.eur(eur))
                }
                LabeledContent("Aktueller Kurs", value: Format.price(position.currentPrice, currency: position.currency))
                LabeledContent("Investiert", value: Format.eur(position.investedEur))
                if let allocation = position.allocationPct {
                    LabeledContent("Anteil am Depot", value: Format.pct(allocation, signed: false))
                }
                LabeledContent("Depot", value: Format.accountName(position.account))
                if let isin = position.isin, !isin.isEmpty { LabeledContent("ISIN", value: isin) }
            }
            .monospacedDigit()

            Section("Entwicklung") {
                LabeledContent("1 Monat") { ChangeLabel(pct: position.perf1mPct) }
                LabeledContent("6 Monate") { ChangeLabel(pct: position.perf6mPct) }
                LabeledContent("1 Jahr") { ChangeLabel(pct: position.perf1yPct) }
                if let low = position.low52w, let high = position.high52w, high > low {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("52-Wochen-Spanne").font(.subheadline)
                        RangeBar(low: low, high: high, value: position.currentPrice)
                        HStack {
                            Text(Format.price(low, currency: position.currency))
                            Spacer()
                            Text(Format.price(high, currency: position.currency))
                        }
                        .font(.caption).foregroundStyle(.secondary).monospacedDigit()
                    }
                }
            }

            if position.peRatio != nil || position.dividendYield != nil || position.beta != nil || position.sector != nil {
                Section("Kennzahlen") {
                    if let sector = position.sector { LabeledContent("Sektor", value: sector) }
                    if let pe = position.peRatio { LabeledContent("KGV", value: Format.number(pe, digits: 1)) }
                    if let dy = position.dividendYield { LabeledContent("Dividendenrendite", value: Format.pct(dy, digits: 2, signed: false)) }
                    if let beta = position.beta { LabeledContent("Beta", value: Format.number(beta, digits: 2)) }
                }
                .monospacedDigit()
            }

            Section("Stop-Loss") {
                if let stop {
                    LabeledContent("Status") { Pill(text: stopLabel ?? stop.status, color: Theme.stopStatus(stop)) }
                    if let broker = stop.brokerStop {
                        LabeledContent("Beim Broker") {
                            VStack(alignment: .trailing, spacing: 1) {
                                Text(Format.price(broker, currency: stop.brokerCurrency))
                                if stop.stopInOtherCurrency {
                                    Text("≈ " + Format.price(stop.currentStop, currency: stop.currency))
                                        .font(.caption2).foregroundStyle(.secondary)
                                }
                            }
                            .monospacedDigit()
                        }
                    } else {
                        LabeledContent("Beim Broker", value: "kein Stop")
                    }
                    if let target = stop.targetStop {
                        LabeledContent("Soll (2×ATR)") {
                            PriceStack(value: target, currency: stop.currency, eurUsd: model.eurUsd, font: .body)
                        }
                    }
                    if let distance = stop.distancePct {
                        LabeledContent("Abstand", value: Format.pct(distance, signed: false))
                    }
                    if let risk = stop.riskEur {
                        LabeledContent("Verlust bis Stop", value: Format.eur(risk, digits: 0))
                    }
                } else {
                    Text("Keine Stop-Daten").foregroundStyle(.secondary)
                }
                if let stop, stop.isStoppable {
                    Button(stop.brokerStop == nil ? "Stop eintragen" : "Stop ändern", systemImage: "shield.lefthalf.filled") {
                        sheet = .editStop(StopTarget(stop: stop))
                    }
                }
            }

            Section {
                Button("Kauf/Verkauf erfassen", systemImage: "arrow.left.arrow.right") {
                    sheet = .trade(position, accounts: accounts)
                }
                Button("Limit-Order platzieren", systemImage: "list.bullet.clipboard") {
                    sheet = .order(ticker: position.ticker, action: "buy", currency: position.currency, accounts: accounts)
                }
                Button("Bestand korrigieren", systemImage: "pencil") {
                    sheet = .editPosition(position, stop: stop, accounts: accounts)
                }
                Button("Position löschen", systemImage: "trash", role: .destructive) { confirmDelete = true }
            } footer: {
                Text("„Kauf/Verkauf“ bucht Cash mit. „Korrigieren“ und „Löschen“ ändern nur den Bestand, ohne Cash-Effekt.")
            }
        }
        .navigationTitle(position.displayName)
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $sheet) { $0.view }
        .confirmationDialog("\(position.displayName) aus dem Depot löschen?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Löschen", role: .destructive) {
                Task {
                    do {
                        try await model.send("/api/portfolio/position/delete",
                                             ["account": .string(position.account), "ticker": .string(position.ticker)])
                        dismiss()
                    } catch { self.error = error.localizedDescription }
                }
            }
        } message: {
            Text("Nur für Korrekturen gedacht – für Verkäufe „Kauf/Verkauf erfassen“ verwenden.")
        }
        .errorAlert($error)
    }
}

private struct RangeBar: View {
    var low: Double
    var high: Double
    var value: Double?

    var body: some View {
        GeometryReader { geo in
            let fraction = value.map { min(max(($0 - low) / (high - low), 0), 1) } ?? 0
            ZStack(alignment: .leading) {
                Capsule().fill(LinearGradient(colors: [Theme.loss.opacity(0.5), Theme.amber.opacity(0.5), Theme.gain.opacity(0.5)],
                                              startPoint: .leading, endPoint: .trailing))
                    .frame(height: 6)
                if value != nil {
                    Circle().fill(.white).frame(width: 12, height: 12)
                        .offset(x: geo.size.width * fraction - 6)
                }
            }
            .frame(maxHeight: .infinity)
        }
        .frame(height: 14)
    }
}
