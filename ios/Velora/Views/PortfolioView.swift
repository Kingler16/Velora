import Charts
import SwiftUI
import VeloraKit

struct PortfolioView: View {
    enum Section: String, CaseIterable, Identifiable {
        case positions = "Positionen", performance = "Performance", tax = "Steuer", stops = "Stops", orders = "Orders"
        var id: Self { self }
    }

    enum Extra: Hashable { case strategy, holdings }

    @State private var section = Section.positions
    @State private var sheet: PortfolioSheet?
    @State private var extra: Extra?

    var body: some View {
        NavigationStack {
            RemoteView(path: "/api/app/portfolio") { (data: PortfolioData) in
                List {
                    Picker("Bereich", selection: $section) {
                        ForEach(Section.allCases) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets())

                    switch section {
                    case .positions: PositionsSection(data: data, sheet: $sheet)
                    case .performance: PerformanceSection(data: data)
                    case .tax: TaxSection(data: data)
                    case .stops: StopsSection(data: data)
                    case .orders: OrdersSection(data: data, sheet: $sheet)
                    }
                }
                .navigationDestination(for: Position.self) { position in
                    PositionDetailView(position: position, stop: data.stop(for: position),
                                       stopLabel: data.stop(for: position).map { data.stopLabel($0.status) },
                                       accounts: data.accounts)
                }
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Menu {
                            Button("Kauf/Verkauf erfassen", systemImage: "arrow.left.arrow.right") {
                                sheet = .trade(nil, accounts: data.accounts)
                            }
                            Button("Order platzieren", systemImage: "list.bullet.clipboard") {
                                sheet = .order(ticker: "", action: "buy", currency: "EUR", accounts: data.accounts)
                            }
                            Button("Bestand nachtragen", systemImage: "plus.square.on.square") {
                                sheet = .addPosition(accounts: data.accounts)
                            }
                            Button("Konto anlegen", systemImage: "building.columns") {
                                sheet = .bankAccount(nil)
                            }
                        } label: {
                            Image(systemName: "plus")
                        }
                    }
                }
            }
            .navigationTitle("Depot")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Menu {
                        Button("Strategie & Mandat", systemImage: "scope") { extra = .strategy }
                        Button("Durchschau (Fonds)", systemImage: "square.stack.3d.down.right") { extra = .holdings }
                    } label: {
                        Image(systemName: "square.grid.2x2")
                    }
                }
            }
            .navigationDestination(item: $extra) { extra in
                switch extra {
                case .strategy: StrategyView()
                case .holdings: HoldingsView()
                }
            }
            .sheet(item: $sheet) { $0.view }
        }
    }
}

/// Alle Eingabeformulare des Depots.
enum PortfolioSheet: Identifiable {
    case trade(Position?, accounts: [String])
    case order(ticker: String, action: String, currency: String, accounts: [String])
    case fill(Order)
    case addPosition(accounts: [String])
    case editPosition(Position, stop: Double?, accounts: [String])
    case bankAccount(BankAccount?)

    var id: String {
        switch self {
        case .trade(let p, _): "trade-\(p?.id ?? "")"
        case .order(let t, _, _, _): "order-\(t)"
        case .fill(let o): "fill-\(o.id)"
        case .addPosition: "add"
        case .editPosition(let p, _, _): "edit-\(p.id)"
        case .bankAccount(let b): "bank-\(b?.id ?? "")"
        }
    }

    @ViewBuilder var view: some View {
        switch self {
        case .trade(let p, let accounts): TradeSheet(position: p, accounts: accounts)
        case .order(let t, let a, let c, let accounts): OrderSheet(ticker: t, action: a, currency: c, accounts: accounts)
        case .fill(let o): FillOrderSheet(order: o)
        case .addPosition(let accounts): AddPositionSheet(accounts: accounts)
        case .editPosition(let p, let stop, let accounts): EditPositionSheet(position: p, stop: stop, accounts: accounts)
        case .bankAccount(let b): BankAccountSheet(account: b)
        }
    }
}

// MARK: - Positionen

private struct PositionsSection: View {
    var data: PortfolioData
    @Binding var sheet: PortfolioSheet?
    @Environment(AppModel.self) private var model
    @State private var error: String?

    var body: some View {
        let overview = data.overview
        Section {
            HStack {
                StatTile(title: "Depotwert", value: Format.eur(overview.holdingsValueEur, digits: 0))
                StatTile(title: "G/V gesamt", value: Format.signedEur(overview.totalPnlEur, digits: 0),
                         footnote: Format.pct(overview.totalPnlPct), footnoteColor: Theme.change(overview.totalPnlPct))
            }
            .listRowBackground(Color.clear)
            .listRowInsets(EdgeInsets())
        }

        ForEach(overview.sortedAccounts, id: \.key) { account in
            Section {
                ForEach(account.group.positions.sorted { $0.currentValueEur > $1.currentValueEur }) { position in
                    NavigationLink(value: position) { PositionRow(position: position) }
                        .swipeActions(edge: .leading) {
                            Button("Handeln", systemImage: "arrow.left.arrow.right") {
                                sheet = .trade(position, accounts: data.accounts)
                            }
                            .tint(Theme.accent)
                        }
                }
            } header: {
                HStack {
                    Text(account.group.displayName.isEmpty ? Format.accountName(account.key) : account.group.displayName)
                    Spacer()
                    Text(Format.eur(account.group.totalValue, digits: 0)).monospacedDigit()
                }
            } footer: {
                Text("G/V \(Format.signedEur(account.group.totalPnl, digits: 0))")
            }
        }

        if !overview.bankAccounts.isEmpty {
            Section {
                ForEach(overview.bankAccounts) { account in
                    Button { sheet = .bankAccount(account) } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(account.note.isEmpty ? Format.accountName(account.name) : account.note)
                                    .foregroundStyle(.primary)
                                Text([account.bank, account.interest > 0 ? Format.pct(account.interest, digits: 2, signed: false) + " Zinsen" : nil,
                                      account.isDepotCash ? "Depot-Cash" : nil].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "))
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(Format.eur(account.value)).monospacedDigit().foregroundStyle(.primary)
                        }
                    }
                    .swipeActions {
                        Button("Löschen", systemImage: "trash", role: .destructive) {
                            Task {
                                do { try await model.send("/api/portfolio/bank/delete", ["key": .string(account.name)]) }
                                catch { self.error = error.localizedDescription }
                            }
                        }
                    }
                }
            } header: {
                HStack {
                    Text("Konten & Cash")
                    Spacer()
                    Text(Format.eur(overview.cashTotal, digits: 0)).monospacedDigit()
                }
            }
            .errorAlert($error)
        }
    }
}

struct PositionRow: View {
    var position: Position

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(position.displayName).font(.subheadline.weight(.medium)).lineLimit(1)
                HStack(spacing: 6) {
                    Text(position.ticker)
                    Text("·")
                    Text("\(Format.shares(position.shares)) Stk.")
                    if !position.hasLivePrice { Image(systemName: "exclamationmark.triangle").foregroundStyle(Theme.amber) }
                }
                .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 3) {
                Text(Format.eur(position.currentValueEur)).font(.subheadline.weight(.medium)).monospacedDigit()
                HStack(spacing: 8) {
                    ChangeLabel(pct: position.changePct, font: .caption)
                    Text(Format.pct(position.pnlPct)).font(.caption.weight(.medium)).monospacedDigit()
                        .foregroundStyle(Theme.change(position.pnlPct))
                }
            }
        }
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Performance

private struct PerformanceSection: View {
    var data: PortfolioData

    var body: some View {
        if data.snapshots.count > 1 {
            Section {
                HistoryCard(snapshots: data.snapshots, current: data.overview.totalValueEur)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets())
            }
        }
        if !data.benchmarks.isEmpty {
            Section {
                BenchmarkCard(benchmarks: data.benchmarks)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets())
            }
        }
        Section("Positionen nach Rendite") {
            ForEach(data.overview.positions.sorted { ($0.pnlPct ?? 0) > ($1.pnlPct ?? 0) }) { p in
                HStack {
                    VStack(alignment: .leading) {
                        Text(p.displayName).font(.subheadline).lineLimit(1)
                        Text("1 M \(Format.pct(p.perf1mPct, digits: 0)) · 6 M \(Format.pct(p.perf6mPct, digits: 0)) · 1 J \(Format.pct(p.perf1yPct, digits: 0))")
                            .font(.caption).foregroundStyle(.secondary).monospacedDigit()
                    }
                    Spacer()
                    VStack(alignment: .trailing) {
                        Text(Format.pct(p.pnlPct)).monospacedDigit().foregroundStyle(Theme.change(p.pnlPct))
                        Text(Format.signedEur(p.pnlEur, digits: 0)).font(.caption).monospacedDigit().foregroundStyle(.secondary)
                    }
                }
            }
        }
        Section("Monatsstände") {
            ForEach(data.snapshots.reversed()) { s in
                HStack {
                    Text(s.date?.formatted(.dateTime.month(.wide).year().locale(Format.locale)) ?? s.month)
                    Spacer()
                    VStack(alignment: .trailing) {
                        Text(Format.eur(s.totalValue, digits: 0)).monospacedDigit()
                        if let note = s.note, !note.isEmpty { Text(note).font(.caption).foregroundStyle(.secondary) }
                    }
                }
            }
        }
    }
}

// MARK: - Steuer

private struct TaxSection: View {
    var data: PortfolioData

    var body: some View {
        if let tax = data.taxLoss {
            let perAccount = data.kestMode == "per_account" && !tax.perAccount.isEmpty
            Section {
                Text(perAccount
                     ? "KESt \(Format.pct(tax.taxRate * 100, signed: false)) – Verlustausgleich je Depot (österreichisches Depot führt KESt automatisch ab)."
                     : "KESt \(Format.pct(tax.taxRate * 100, signed: false)) – Verlustausgleich über alle Depots.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            if perAccount {
                ForEach(tax.perAccount.sorted { $0.key < $1.key }, id: \.key) { key, summary in
                    TaxSummarySection(title: Format.accountName(key), summary: summary)
                }
            } else {
                TaxSummarySection(title: "Alle Depots", summary: tax.total)
            }
        } else {
            ContentUnavailableView("Keine Kursdaten", systemImage: "percent", description: Text("Für die Steuerübersicht braucht der Server aktuelle Marktdaten."))
        }
    }
}

private struct TaxSummarySection: View {
    var title: String
    var summary: TaxLossSummary

    var body: some View {
        Section(title) {
            LabeledContent("Unrealisierte Gewinne", value: Format.eur(summary.totalGains))
            LabeledContent("Unrealisierte Verluste", value: Format.eur(summary.totalLosses))
            LabeledContent("KESt auf Gewinne", value: Format.eur(summary.potentialTax))
            LabeledContent("KESt nach Verlustausgleich", value: Format.eur(summary.netTax))
            if summary.taxSavings > 0 {
                Label("Verluste realisieren spart bis zu \(Format.eur(summary.taxSavings))", systemImage: "lightbulb")
                    .font(.subheadline).foregroundStyle(Theme.gain)
            }
            ForEach(summary.losses) { item in
                HStack {
                    Text(item.name).lineLimit(1)
                    Spacer()
                    Text(Format.signedEur(item.pnlEur)).monospacedDigit().foregroundStyle(Theme.loss)
                }
                .font(.subheadline)
            }
        }
        .monospacedDigit()
    }
}

// MARK: - Stops

private struct StopsSection: View {
    var data: PortfolioData

    var body: some View {
        if let stops = data.stops {
            Section {
                HStack {
                    StatTile(title: "Ohne Stop", value: "\(stops.withoutStop)", footnote: "\(stops.withStop) mit Stop")
                    StatTile(title: "Ungesichert", value: Format.eur(stops.unprotectedEur, digits: 0),
                             footnote: "Risiko bis Stop \(Format.eur(stops.totalRiskEur, digits: 0))")
                }
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets())
            }
            Section("Positionen") {
                ForEach(stops.positions.sorted { ($0.needsAttention ? 0 : 1, -($0.valueEur ?? 0)) < ($1.needsAttention ? 0 : 1, -($1.valueEur ?? 0)) }) { s in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(s.name.isEmpty ? s.ticker : s.name).font(.subheadline.weight(.medium)).lineLimit(1)
                            Spacer()
                            Pill(text: data.stopLabel(s.status), color: s.needsAttention ? Theme.amber : Theme.gain)
                        }
                        HStack(spacing: 12) {
                            Text("Kurs \(Format.price(s.currentPrice, currency: s.currency))")
                            if let stop = s.currentStop { Text("Stop \(Format.price(stop, currency: s.currency))") }
                            if let target = s.targetStop { Text("Soll \(Format.price(target, currency: s.currency))") }
                        }
                        .font(.caption).foregroundStyle(.secondary).monospacedDigit()
                    }
                }
            }
        } else {
            ContentUnavailableView("Keine Stop-Übersicht", systemImage: "shield.slash")
        }
    }
}

// MARK: - Orders

private struct OrdersSection: View {
    var data: PortfolioData
    @Binding var sheet: PortfolioSheet?
    @Environment(AppModel.self) private var model
    @State private var error: String?

    var body: some View {
        if data.openOrders.isEmpty {
            ContentUnavailableView("Keine offenen Orders", systemImage: "list.bullet.clipboard",
                                   description: Text("Platzierte Limit-Orders erscheinen hier, bis sie ausgeführt oder storniert sind."))
        } else {
            Section {
                ForEach(data.openOrders) { order in
                    OrderRow(order: order)
                        .swipeActions {
                            Button("Storno", systemImage: "xmark", role: .destructive) {
                                Task {
                                    do { try await model.send("/api/orders/cancel", ["id": .string(order.id)]) }
                                    catch { self.error = error.localizedDescription }
                                }
                            }
                        }
                        .swipeActions(edge: .leading) {
                            Button("Ausgeführt", systemImage: "checkmark") { sheet = .fill(order) }
                                .tint(Theme.gain)
                        }
                }
            } footer: {
                Text("Nach rechts wischen: ausgeführt (bucht ins Depot). Nach links: stornieren.")
            }
            .errorAlert($error)
        }
    }
}

struct OrderRow: View {
    var order: Order

    var body: some View {
        HStack {
            Pill(text: order.action == "buy" ? "Kauf" : "Verkauf", color: order.action == "buy" ? Theme.gain : Theme.loss)
            VStack(alignment: .leading, spacing: 2) {
                Text(order.ticker).font(.subheadline.weight(.medium))
                Text("\(Format.accountName(order.account)) · \(Format.date(order.placedDate))")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text("\(Format.shares(order.shares)) Stk.").font(.subheadline).monospacedDigit()
                Text("Limit \(Format.price(order.limitPrice, currency: order.currency))").font(.caption).foregroundStyle(.secondary).monospacedDigit()
            }
        }
    }
}
