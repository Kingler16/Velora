import SwiftUI
import VeloraKit

struct MarketView: View {
    enum Section: String, CaseIterable, Identifiable {
        case overview = "Überblick", news = "News", calendar = "Termine"
        var id: Self { self }
    }

    @State private var section = Section.overview

    var body: some View {
        NavigationStack {
            RemoteView(path: "/api/app/market") { (data: MarketData) in
                List {
                    Picker("Bereich", selection: $section) {
                        ForEach(Section.allCases) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets())

                    switch section {
                    case .overview: MarketOverview(data: data)
                    case .news: NewsSections(news: data.news)
                    case .calendar: CalendarSections(calendar: data.calendar)
                    }
                }
            }
            .navigationTitle("Markt")
        }
    }
}

private struct MarketOverview: View {
    var data: MarketData

    var body: some View {
        Section("Indizes") {
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                ForEach(data.indices) { index in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(index.name).font(.caption.weight(.semibold)).lineLimit(1)
                        Text(index.name == "EUR/USD" ? Format.number(index.value, digits: 4) : Format.number(index.value, digits: 0))
                            .font(.subheadline).monospacedDigit()
                        ChangeLabel(pct: index.changePct, font: .caption)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(.vertical, 4)
        }

        if let fg = data.macro?.fearGreed, let value = fg.value {
            Section("Fear & Greed Index") {
                HStack(spacing: 16) {
                    Gauge(value: value, in: 0...100) {
                        Text("F&G")
                    } currentValueLabel: {
                        Text(Format.number(value, digits: 0))
                    }
                    .gaugeStyle(.accessoryCircular)
                    .tint(Gradient(colors: [Theme.loss, Theme.amber, Theme.gain]))
                    .scaleEffect(1.3)
                    .frame(width: 70, height: 70)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(fg.ratingLabel).font(.title3.weight(.semibold))
                        Group {
                            if let v = fg.previousWeek { Text("Vorwoche \(Format.number(v, digits: 0))") }
                            if let v = fg.previousMonth { Text("Vormonat \(Format.number(v, digits: 0))") }
                            if let v = fg.previousYear { Text("Vorjahr \(Format.number(v, digits: 0))") }
                        }
                        .font(.caption).foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 6)
            }
        }

        if let macro = data.macro {
            MacroSection(title: "USA", values: macro.us, labels: MacroData.usLabels)
            MacroSection(title: "Eurozone", values: macro.eu, labels: MacroData.euLabels)
        }

        if !data.sectorHeatmap.isEmpty {
            Section("Sektoren im Depot heute") {
                ForEach(data.sectorHeatmap.sorted { $0.value > $1.value }, id: \.key) { sector, change in
                    HStack {
                        Text(sector)
                        Spacer()
                        ChangeLabel(pct: change)
                    }
                }
            }
        }

        if let status = data.status {
            Section { DataStatusFooter(status: status) }
                .listRowBackground(Color.clear)
        }
    }
}

private struct MacroSection: View {
    var title: String
    var values: [String: MacroValue]
    var labels: [(key: String, label: String, unit: String)]

    var body: some View {
        let known = labels.filter { values[$0.key]?.value != nil }
        if !known.isEmpty {
            Section(title) {
                ForEach(known, id: \.key) { item in
                    let entry = values[item.key]!
                    LabeledContent {
                        VStack(alignment: .trailing, spacing: 1) {
                            Text(Format.number(entry.value, digits: item.key == "eur_usd" ? 4 : 2) + (item.unit.isEmpty ? "" : " \(item.unit)"))
                                .monospacedDigit()
                                .foregroundStyle(item.key == "yield_curve_spread" && (entry.value ?? 0) < 0 ? Theme.loss : .primary)
                            if let date = entry.date { Text(Format.date(date)).font(.caption2).foregroundStyle(.tertiary) }
                        }
                    } label: {
                        Text(item.label)
                        if let note = entry.note { Text(note) }
                    }
                }
            }
        }
    }
}

private struct NewsSections: View {
    var news: NewsData?

    var body: some View {
        if let news {
            if !news.bloombergHeadlines.isEmpty {
                Section("Bloomberg") { ForEach(news.bloombergHeadlines) { NewsRow(item: $0) } }
            }
            if !news.macroNews.isEmpty {
                Section("Makro") { ForEach(news.macroNews) { NewsRow(item: $0) } }
            }
            if !news.positionNews.isEmpty {
                Section("Zu deinen Positionen") {
                    ForEach(news.positionNews.sorted { $0.key < $1.key }, id: \.key) { ticker, items in
                        DisclosureGroup {
                            if let s = news.sentiment[ticker], let bull = s.bullish {
                                Text("Analysten: \(Format.pct(bull, digits: 0, signed: false)) positiv · \(Format.pct(s.bearish, digits: 0, signed: false)) negativ")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            ForEach(items) { NewsRow(item: $0) }
                        } label: {
                            HStack {
                                Text(ticker).font(.subheadline.weight(.semibold))
                                Spacer()
                                Text("\(items.count)").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
            if !news.opportunities.isEmpty {
                Section("Ideen") { ForEach(news.opportunities) { NewsRow(item: $0) } }
            }
        } else {
            ContentUnavailableView("Keine News", systemImage: "newspaper")
        }
    }
}

struct NewsRow: View {
    var item: NewsItem

    var body: some View {
        let content = VStack(alignment: .leading, spacing: 4) {
            Text(item.title).font(.subheadline.weight(.medium)).foregroundStyle(.primary).lineLimit(3)
            if let d = item.description, !d.isEmpty {
                Text(d).font(.caption).foregroundStyle(.secondary).lineLimit(2)
            }
            Text([item.host, item.age ?? (item.published.map { Format.relative($0) })].compactMap { $0 }.joined(separator: " · "))
                .font(.caption2).foregroundStyle(.tertiary)
        }
        if let link = item.link {
            Link(destination: link) { content }
        } else {
            content
        }
    }
}

private struct CalendarSections: View {
    var calendar: CalendarData?

    var body: some View {
        if let calendar {
            if let status = calendar.marketStatus {
                Section("Börsen heute") {
                    ExchangeRow(name: "Wiener Börse", open: status.wienOpen)
                    ExchangeRow(name: "Xetra", open: status.xetraOpen)
                    ExchangeRow(name: "NYSE", open: status.nyseOpen)
                }
            }
            if !calendar.earnings.isEmpty {
                Section("Quartalszahlen") {
                    ForEach(calendar.earnings.sorted { $0.date < $1.date }) { e in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(e.name.isEmpty ? e.ticker : e.name).font(.subheadline)
                                Text(e.ticker).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(Format.date(e.date)).font(.subheadline).monospacedDigit()
                        }
                    }
                }
            }
            if !calendar.macroEvents.isEmpty {
                Section("Makro-Termine") {
                    ForEach(calendar.macroEvents) { e in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(e.name).font(.subheadline)
                                if let c = e.category { Text(c).font(.caption).foregroundStyle(.secondary) }
                            }
                            Spacer()
                            VStack(alignment: .trailing) {
                                Text(Format.date(e.date)).font(.subheadline).monospacedDigit()
                                if let d = e.daysUntil { Text(d == 0 ? "heute" : "in \(d) Tagen").font(.caption).foregroundStyle(.secondary) }
                            }
                        }
                    }
                }
            }
            if let holidays = calendar.marketStatus?.upcomingHolidays, !holidays.isEmpty {
                Section("Feiertage") {
                    ForEach(holidays) { h in
                        LabeledContent {
                            Text(Format.date(h.date)).monospacedDigit()
                        } label: {
                            Text(h.name)
                            if let ex = h.exchanges { Text(ex) }
                        }
                    }
                }
            }
        } else {
            ContentUnavailableView("Keine Termine", systemImage: "calendar")
        }
    }
}

private struct ExchangeRow: View {
    var name: String
    var open: Bool

    var body: some View {
        LabeledContent(name) {
            Label(open ? "Handelstag" : "geschlossen", systemImage: open ? "checkmark.circle.fill" : "moon.fill")
                .foregroundStyle(open ? Theme.gain : .secondary)
        }
    }
}
