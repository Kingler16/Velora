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
                    case .stops: StopsSection(data: data, sheet: $sheet)
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
                            if let stops = data.stops?.positions.filter(\.isStoppable), !stops.isEmpty {
                                Menu("Stop eintragen", systemImage: "shield.lefthalf.filled") {
                                    ForEach(stops) { stop in
                                        Button(stop.displayName) { sheet = .editStop(StopTarget(stop: stop)) }
                                    }
                                }
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
    case fillStop(StopPosition)
    case addPosition(accounts: [String])
    case editPosition(Position, stop: StopPosition?, accounts: [String])
    case editStop(StopTarget)
    case bankAccount(BankAccount?)

    var id: String {
        switch self {
        case .trade(let p, _): "trade-\(p?.id ?? "")"
        case .order(let t, _, _, _): "order-\(t)"
        case .fill(let o): "fill-\(o.id)"
        case .fillStop(let s): "fillstop-\(s.id)"
        case .addPosition: "add"
        case .editPosition(let p, _, _): "edit-\(p.id)"
        case .editStop(let t): "stop-\(t.id)"
        case .bankAccount(let b): "bank-\(b?.id ?? "")"
        }
    }

    @ViewBuilder var view: some View {
        switch self {
        case .trade(let p, let accounts): TradeSheet(position: p, accounts: accounts)
        case .order(let t, let a, let c, let accounts): OrderSheet(ticker: t, action: a, currency: c, accounts: accounts)
        case .fill(let o): FillOrderSheet(order: o)
        case .fillStop(let s): FillStopSheet(stop: s)
        case .addPosition(let accounts): AddPositionSheet(accounts: accounts)
        case .editPosition(let p, let stop, let accounts): EditPositionSheet(position: p, stop: stop, accounts: accounts)
        case .editStop(let t): EditStopSheet(target: t)
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
                HistoryCard(snapshots: data.snapshots, current: data.overview.totalValueEur,
                            currentHoldings: data.overview.holdingsValueEur)
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
    @Binding var sheet: PortfolioSheet?

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
            Section {
                ForEach(stops.positions.sorted { ($0.needsAttention ? 0 : 1, -($0.valueEur ?? 0)) < ($1.needsAttention ? 0 : 1, -($1.valueEur ?? 0)) }) { s in
                    Button {
                        if s.isStoppable { sheet = .editStop(StopTarget(stop: s)) }
                    } label: {
                        StopRow(stop: s, label: data.stopLabel(s.status), eurUsd: data.eurUsd)
                    }
                    .tint(.primary)
                }
            } header: {
                Text("Positionen")
            } footer: {
                Text("Tippen, um den Stop so einzutragen, wie er beim Broker steht – in € oder $. Soll = Kurs − 2×ATR.")
            }
        } else {
            ContentUnavailableView("Keine Stop-Übersicht", systemImage: "shield.slash")
        }
    }
}

private struct StopRow: View {
    var stop: StopPosition
    var label: String
    var eurUsd: Double?

    var body: some View {
        let s = stop
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(s.displayName).font(.subheadline.weight(.medium)).lineLimit(1)
                Spacer()
                Pill(text: label, color: Theme.stopStatus(s))
            }
            HStack(alignment: .top, spacing: 0) {
                column("Kurs", Format.price(s.currentPrice, currency: s.currency),
                       Format.eurHint(s.currentPrice, currency: s.currency, eurUsd: eurUsd))
                if let broker = s.brokerStop {
                    column("Stop", Format.price(broker, currency: s.brokerCurrency),
                           s.stopInOtherCurrency ? "≈ " + Format.price(s.currentStop, currency: s.currency)
                                                 : Format.eurHint(broker, currency: s.brokerCurrency, eurUsd: eurUsd),
                           color: s.status == "ungueltig" ? Theme.loss : .primary)
                } else {
                    column("Stop", "–", nil, color: s.needsAttention ? Theme.amber : .secondary)
                }
                if let target = s.targetStop {
                    column("Soll", Format.price(target, currency: s.currency),
                           Format.eurHint(target, currency: s.currency, eurUsd: eurUsd))
                }
            }
            if let hint = s.hint {
                Text(hint).font(.caption2).foregroundStyle(.tertiary)
            }
        }
        .padding(.vertical, 2)
    }

    private func column(_ title: String, _ value: String, _ sub: String?, color: Color = .primary) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(title).font(.caption2).foregroundStyle(.secondary)
            Text(value).font(.footnote.weight(.medium)).foregroundStyle(color)
            if let sub { Text(sub).font(.caption2).foregroundStyle(.secondary) }
        }
        .monospacedDigit()
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// MARK: - Orders

/// Alles, was beim Broker offen liegt: Stop-Orders (aus den gesetzten Stops) und Limit-Orders.
private struct OrdersSection: View {
    var data: PortfolioData
    @Binding var sheet: PortfolioSheet?
    @Environment(AppModel.self) private var model
    @State private var error: String?

    var body: some View {
        if data.openOrderCount == 0 {
            ContentUnavailableView {
                Label("Keine offenen Orders", systemImage: "list.bullet.clipboard")
            } description: {
                Text("Stop-Orders erscheinen hier, sobald du bei einer Position den Stop einträgst. Limit-Orders über + → „Order platzieren“.")
            }
        } else {
            Section {
                HStack {
                    StatTile(title: "Offen", value: "\(data.openOrderCount)",
                             footnote: "\(data.stopOrders.count) Stop · \(data.openOrders.count) Limit")
                    StatTile(title: "Abgesichert", value: Format.eur(data.stopOrders.reduce(0) { $0 + ($1.valueEur ?? 0) }, digits: 0),
                             footnote: "Depotwert mit Stop")
                }
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets())
            }

            if !data.stopOrders.isEmpty {
                ForEach(groupedStops, id: \.account) { group in
                    Section {
                        ForEach(group.stops) { stop in
                            Button { sheet = .editStop(StopTarget(stop: stop)) } label: {
                                StopOrderRow(stop: stop, eurUsd: data.eurUsd)
                            }
                            .tint(.primary)
                            .swipeActions(edge: .leading) {
                                Button("Ausgelöst", systemImage: "checkmark") { sheet = .fillStop(stop) }
                                    .tint(Theme.accent)
                            }
                        }
                    } header: {
                        Text("Stop · \(Format.accountName(group.account))")
                    } footer: {
                        if group.account == groupedStops.last?.account {
                            Text("Tippen: Stop ändern. Nach rechts wischen: ausgelöst (bucht den Verkauf ins Depot).")
                        }
                    }
                }
            }

            if !data.openOrders.isEmpty {
                Section {
                    ForEach(data.openOrders) { order in
                        OrderRow(order: order, eurUsd: data.eurUsd)
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
                                    .tint(Theme.accent)
                            }
                    }
                } header: {
                    Text("Limit")
                } footer: {
                    Text("Nach rechts wischen: ausgeführt (bucht ins Depot). Nach links: stornieren.")
                }
                .errorAlert($error)
            }
        }
    }

    private var groupedStops: [(account: String, stops: [StopPosition])] {
        Dictionary(grouping: data.stopOrders, by: \.account)
            .map { ($0.key, $0.value) }
            .sorted { $0.account < $1.account }
    }
}

private struct StopOrderRow: View {
    var stop: StopPosition
    var eurUsd: Double?

    var body: some View {
        let s = stop
        HStack(spacing: 12) {
            IconBadge(systemImage: "shield.lefthalf.filled", color: Theme.stopStatus(s), size: 34)
            VStack(alignment: .leading, spacing: 2) {
                Text(s.displayName).font(.subheadline.weight(.semibold)).lineLimit(1)
                Text(subtitle).font(.caption).foregroundStyle(.secondary).lineLimit(1).monospacedDigit()
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 1) {
                Text(Format.price(s.brokerStop, currency: s.brokerCurrency)).font(.subheadline.weight(.semibold))
                if s.stopInOtherCurrency {
                    Text("≈ " + Format.price(s.currentStop, currency: s.currency)).font(.caption2).foregroundStyle(.secondary)
                } else if let hint = Format.eurHint(s.brokerStop, currency: s.brokerCurrency, eurUsd: eurUsd) {
                    Text(hint).font(.caption2).foregroundStyle(.secondary)
                }
            }
            .monospacedDigit()
        }
        .padding(.vertical, 2)
    }

    private var subtitle: String {
        var parts = ["Verkauf"]
        if let shares = stop.shares { parts.append("\(Format.shares(shares)) Stk.") }
        if let price = stop.currentPrice { parts.append("Kurs \(Format.price(price, currency: stop.currency))") }
        if let pct = stop.distancePct { parts.append(Format.pct(pct)) }
        return parts.joined(separator: " · ")
    }
}

struct OrderRow: View {
    var order: Order
    var eurUsd: Double?

    var body: some View {
        HStack(spacing: 12) {
            IconBadge(systemImage: order.action == "buy" ? "cart.fill" : "arrow.down.right",
                      color: order.action == "buy" ? Theme.accent : Theme.loss, size: 34)
            VStack(alignment: .leading, spacing: 2) {
                Text("\(order.action == "buy" ? "Kauf" : "Verkauf") · \(order.ticker)").font(.subheadline.weight(.semibold))
                Text(subtitle).font(.caption).foregroundStyle(order.isExpired() ? Theme.amber : .secondary).lineLimit(1)
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 1) {
                Text(Format.price(order.limitPrice, currency: order.currency)).font(.subheadline.weight(.semibold))
                Text("\(Format.shares(order.shares)) Stk.\(order.volume.map { " · " + Format.price($0, currency: order.currency) } ?? "")")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            .monospacedDigit()
        }
        .padding(.vertical, 2)
    }

    private var subtitle: String {
        var parts = [Format.accountName(order.account)]
        if let until = order.validUntil {
            parts.append(order.isExpired() ? "abgelaufen \(Format.date(until))" : "gültig bis \(Format.date(until))")
        } else if let placed = order.placedDate {
            parts.append("seit \(Format.date(placed))")
        }
        return parts.joined(separator: " · ")
    }
}
