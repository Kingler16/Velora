import Charts
import SwiftUI
import VeloraKit

struct DashboardView: View {
    @Environment(AppModel.self) private var model
    @State private var showSettings = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            RemoteView(path: "/api/app/dashboard") { (data: DashboardData) in
                ScrollView {
                    VStack(spacing: 16) {
                        HeaderCard(overview: data.overview)
                        if !data.actionable.isEmpty {
                            ActionableCard(recommendations: data.actionable, eurUsd: data.eurUsd)
                        }
                        IndexStrip(indices: data.indices)
                        if let briefing = data.latestBriefing { LatestBriefingCard(briefing: briefing) }
                        if data.snapshots.count > 1 {
                            HistoryCard(snapshots: data.snapshots, current: data.overview.totalValueEur)
                        }
                        AllocationCard(overview: data.overview)
                        if !data.benchmarks.isEmpty { BenchmarkCard(benchmarks: data.benchmarks) }
                        if let status = data.status { DataStatusFooter(status: status) }
                    }
                    .padding()
                }
            }
            .navigationTitle("Velora")
            .navigationDestination(for: Briefing.self) { BriefingDetailView(briefing: $0) }
            .navigationDestination(for: Recommendation.self) { RecommendationDetailView(recommendation: $0) }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        Task {
                            do { try await model.refreshServerData() } catch { self.error = error.localizedDescription }
                        }
                    } label: {
                        if model.refreshRunning { ProgressView() } else { Image(systemName: "arrow.clockwise") }
                    }
                    .disabled(model.refreshRunning)
                    .accessibilityLabel("Marktdaten am Server aktualisieren")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showSettings = true } label: { Image(systemName: "gearshape") }
                        .accessibilityLabel("Einstellungen")
                }
            }
            .sheet(isPresented: $showSettings) { SettingsView() }
            .errorAlert($error)
        }
    }
}

private struct HeaderCard: View {
    var overview: PortfolioOverview

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Gesamtvermögen").font(.subheadline).foregroundStyle(.secondary)
                Text(Format.eur(overview.totalValueEur))
                    .font(.system(size: 38, weight: .bold, design: .rounded))
                    .monospacedDigit()
                    .minimumScaleFactor(0.6)
                    .lineLimit(1)
                HStack(spacing: 6) {
                    Text("Heute").font(.subheadline).foregroundStyle(.secondary)
                    ChangeLabel(pct: overview.holdingsValueEur > 0
                                ? overview.dayChangeEur / (overview.holdingsValueEur - overview.dayChangeEur) * 100 : nil,
                                eur: overview.dayChangeEur)
                }
            }
            Grid(horizontalSpacing: 10, verticalSpacing: 10) {
                GridRow {
                    StatTile(title: "Gewinn/Verlust", value: Format.signedEur(overview.totalPnlEur, digits: 0),
                             footnote: Format.pct(overview.totalPnlPct), footnoteColor: Theme.change(overview.totalPnlPct))
                    StatTile(title: "Wertpapiere", value: Format.eur(overview.holdingsValueEur, digits: 0),
                             footnote: "\(overview.positionCount) Positionen")
                }
                GridRow {
                    StatTile(title: "Investiert", value: Format.eur(overview.totalInvestedEur, digits: 0))
                    StatTile(title: "Cash", value: Format.eur(overview.cashTotal, digits: 0),
                             footnote: overview.cashPct.map { Format.pct($0, signed: false) + " Anteil" })
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            LinearGradient(colors: [Theme.cyan.opacity(0.18), Theme.indigo.opacity(0.12), .clear],
                           startPoint: .topLeading, endPoint: .bottomTrailing),
            in: .rect(cornerRadius: 24)
        )
        .background(.background.secondary, in: .rect(cornerRadius: 24))
    }
}

struct IndexStrip: View {
    var indices: [IndexQuote]

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(indices) { index in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(index.name).font(.caption.weight(.semibold))
                        Text(index.name == "EUR/USD" ? Format.number(index.value, digits: 4) : Format.number(index.value, digits: 0))
                            .font(.caption).monospacedDigit().foregroundStyle(.secondary)
                        ChangeLabel(pct: index.changePct, font: .caption)
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(.background.secondary, in: .rect(cornerRadius: 12))
                }
            }
        }
        .scrollClipDisabled()
    }
}

struct HistoryCard: View {
    var snapshots: [Snapshot]
    var current: Double?

    private var points: [(date: Date, value: Double)] {
        var p = snapshots.compactMap { s in s.date.map { ($0, s.totalValue) } }.sorted { $0.0 < $1.0 }
        if let current { p.append((.now, current)) }
        return p
    }

    /// Y-Bereich eng um die tatsächlichen Werte. Eine AreaMark füllt sonst bis 0 und zieht
    /// die Achse mit – dann sehen 62 → 66 Tsd. € wie eine flache Linie aus.
    private var yDomain: ClosedRange<Double> {
        let values = points.map(\.value)
        guard let lo = values.min(), let hi = values.max() else { return 0...1 }
        let pad = max((hi - lo) * 0.15, hi * 0.005, 1)
        return (lo - pad)...(hi + pad)
    }

    var body: some View {
        let domain = yDomain
        Card(title: "Vermögensverlauf", subtitle: "Monatsstände") {
            Chart(points, id: \.date) { point in
                AreaMark(x: .value("Monat", point.date), yStart: .value("Basis", domain.lowerBound), yEnd: .value("Wert", point.value))
                    .foregroundStyle(LinearGradient(colors: [Theme.accent.opacity(0.35), .clear], startPoint: .top, endPoint: .bottom))
                    .interpolationMethod(.monotone)
                LineMark(x: .value("Monat", point.date), y: .value("Wert", point.value))
                    .foregroundStyle(Theme.accent)
                    .interpolationMethod(.monotone)
            }
            .chartYScale(domain: domain)
            .chartYAxis {
                AxisMarks(position: .leading) { value in
                    AxisGridLine()
                    AxisValueLabel { if let v = value.as(Double.self) { Text(Format.eurShort(v)) } }
                }
            }
            .chartXAxis {
                AxisMarks(values: .stride(by: .month, count: 3)) { _ in
                    AxisGridLine()
                    AxisValueLabel(format: .dateTime.month(.abbreviated).year(.twoDigits).locale(Format.locale))
                }
            }
            .frame(height: 190)
        }
    }
}

private struct AllocationCard: View {
    var overview: PortfolioOverview
    @State private var mode = 0

    private var slices: [(name: String, value: Double)] {
        switch mode {
        case 0:
            let sorted = overview.positions.sorted { $0.currentValueEur > $1.currentValueEur }
            var s = sorted.prefix(6).map { ($0.displayName, $0.currentValueEur) }
            let rest = sorted.dropFirst(6).reduce(0) { $0 + $1.currentValueEur }
            if rest > 0 { s.append(("Übrige", rest)) }
            if overview.cashTotal > 0 { s.append(("Cash", overview.cashTotal)) }
            return s
        case 1:
            return overview.regionExposure.sorted { $0.value > $1.value }.map { ($0.key, $0.value) }
        default:
            return overview.sectorBreakdown.sorted { $0.value > $1.value }.map { ($0.key, $0.value) }
        }
    }

    var body: some View {
        let slices = slices
        let total = slices.reduce(0) { $0 + $1.value }
        Card(title: "Aufteilung") {
            Picker("Ansicht", selection: $mode) {
                Text("Positionen").tag(0)
                Text("Regionen").tag(1)
                Text("Sektoren").tag(2)
            }
            .pickerStyle(.segmented)

            HStack(alignment: .center, spacing: 16) {
                Chart(Array(slices.enumerated()), id: \.offset) { i, slice in
                    SectorMark(angle: .value("Wert", slice.value), innerRadius: .ratio(0.62), angularInset: 1.5)
                        .foregroundStyle(Theme.series[i % Theme.series.count])
                        .cornerRadius(3)
                }
                .frame(width: 130, height: 130)

                VStack(alignment: .leading, spacing: 5) {
                    ForEach(Array(slices.enumerated()), id: \.offset) { i, slice in
                        HStack(spacing: 6) {
                            Circle().fill(Theme.series[i % Theme.series.count]).frame(width: 8, height: 8)
                            Text(slice.name).font(.caption).lineLimit(1)
                            Spacer(minLength: 4)
                            Text(Format.pct(total > 0 ? slice.value / total * 100 : 0, digits: 0, signed: false))
                                .font(.caption).monospacedDigit().foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
    }
}

/// Offene Empfehlungen gleich unter dem Vermögen – das, was heute zu tun ist.
private struct ActionableCard: View {
    var recommendations: [Recommendation]
    var eurUsd: Double?

    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Label {
                    Text("Zu tun").font(.headline)
                } icon: {
                    Image(systemName: "bell.badge.fill").foregroundStyle(Theme.amber)
                }
                Text("\(recommendations.count)")
                    .font(.caption.weight(.bold)).monospacedDigit()
                    .padding(.horizontal, 7).padding(.vertical, 2)
                    .background(Theme.amber.opacity(0.2), in: .capsule)
                    .foregroundStyle(Theme.amber)
                Spacer()
                Button("Alle") {
                    model.advisorSection = .recommendations
                    model.selectedTab = .advisor
                }
                .font(.subheadline.weight(.medium))
            }
            ForEach(recommendations.prefix(3)) { rec in
                NavigationLink(value: rec) {
                    RecommendationRow(recommendation: rec, eurUsd: eurUsd)
                        .contentShape(.rect)
                }
                .buttonStyle(.plain)
                if rec.id != recommendations.prefix(3).last?.id { Divider() }
            }
            if recommendations.count > 3 {
                Text("+ \(recommendations.count - 3) weitere im Berater").font(.footnote).foregroundStyle(.secondary)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.amber.opacity(0.06), in: .rect(cornerRadius: 20))
        .background(.background.secondary, in: .rect(cornerRadius: 20))
        .overlay(RoundedRectangle(cornerRadius: 20).strokeBorder(Theme.amber.opacity(0.25)))
    }
}

private struct LatestBriefingCard: View {
    var briefing: Briefing

    var body: some View {
        NavigationLink(value: briefing) {
            Card(title: "Letztes Briefing", subtitle: Format.date(briefing.date, time: true)) {
                Text(briefing.summary).font(.subheadline).foregroundStyle(.primary).multilineTextAlignment(.leading)
                    .lineLimit(4)
                HStack {
                    if briefing.recommendationCount > 0 {
                        Pill(text: briefing.recommendationCount == 1 ? "1 Empfehlung" : "\(briefing.recommendationCount) Empfehlungen", color: Theme.violet)
                    }
                    if briefing.hadActions { Pill(text: "Handlungsbedarf", color: Theme.amber) }
                    Spacer()
                    if briefing.hasFullText {
                        Text("Lesen").font(.subheadline.weight(.medium)).foregroundStyle(Theme.accent)
                        Image(systemName: "chevron.right").font(.caption).foregroundStyle(Theme.accent)
                    }
                }
            }
        }
        .buttonStyle(.plain)
    }
}

struct BenchmarkCard: View {
    var benchmarks: [Benchmark]

    var body: some View {
        Card(title: "Märkte heute") {
            Chart(benchmarks.filter { $0.changePct != nil }) { b in
                BarMark(x: .value("Veränderung", b.changePct ?? 0), y: .value("Index", b.name))
                    .foregroundStyle(Theme.change(b.changePct))
                    .annotation(position: (b.changePct ?? 0) >= 0 ? .trailing : .leading) {
                        Text(Format.pct(b.changePct)).font(.caption2).monospacedDigit().foregroundStyle(.secondary)
                    }
            }
            .chartXAxis(.hidden)
            .frame(height: CGFloat(benchmarks.count) * 28)
        }
    }
}

struct DataStatusFooter: View {
    var status: ServerStatus

    var body: some View {
        let market = status.market
        Label {
            if status.refreshRunning {
                Text("Daten werden am Server aktualisiert …")
            } else if let market, market.available {
                Text("Marktdaten \(Format.age(minutes: market.ageMinutes))")
            } else {
                Text("Noch keine Marktdaten – oben links aktualisieren")
            }
        } icon: {
            Image(systemName: (market?.ageMinutes ?? .infinity) < 360 ? "checkmark.circle" : "clock.badge.exclamationmark")
        }
        .font(.footnote)
        .foregroundStyle(.secondary)
        .frame(maxWidth: .infinity)
        .padding(.top, 4)
    }
}
