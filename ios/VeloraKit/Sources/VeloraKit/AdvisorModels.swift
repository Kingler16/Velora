import Foundation

public struct Briefing: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { date }
    public var date: String
    public var summary: String
    public var fullText: String?
    public var recommendationCount: Int
    public var hadActions: Bool
    public var marketRegime: String?

    enum CodingKeys: String, CodingKey {
        case date, summary
        case fullText = "full_text", recommendationCount = "recommendation_count"
        case hadActions = "had_actions", marketRegime = "market_regime"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        date = c(.date, default: "")
        summary = c(.summary, default: "")
        fullText = c(.fullText)
        recommendationCount = c(.recommendationCount, default: 0)
        hadActions = c.flag(.hadActions)
        marketRegime = c(.marketRegime)
    }

    public var parsedDate: Date? { VeloraDate.parse(date) }
    public var hasFullText: Bool { !(fullText ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
}

public struct Thesis: Decodable, Sendable, Hashable {
    public var thesis: String
    public var date: String?

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        thesis = c(.thesis, default: "")
        date = c(.date)
    }

    enum CodingKeys: String, CodingKey { case thesis, date }
}

public struct Notes: Decodable, Sendable {
    public var marketRegime: String?
    public var keyInsights: [String]
    public var positionTheses: [String: Thesis]

    enum CodingKeys: String, CodingKey {
        case marketRegime = "market_regime", keyInsights = "key_insights", positionTheses = "position_theses"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        marketRegime = c(.marketRegime)
        // Insights sind meist Strings, ältere Einträge Objekte mit "insight"/"text".
        let raw: [JSONValue] = c(.keyInsights, default: [])
        keyInsights = raw.compactMap { value in
            switch value {
            case .string(let s): s
            case .object(let o): (o["insight"] ?? o["text"])?.display
            default: nil
            }
        }
        positionTheses = c(.positionTheses, default: [:])
    }
}

public struct Recommendation: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { "\(ticker)|\(date)|\(action)" }
    public var ticker: String
    public var action: String
    public var entryPrice: Double?
    public var targetPrice: Double?
    public var stopLoss: Double?
    public var reasoning: String
    public var date: String
    public var status: String
    public var outcome: String?
    public var currency: String

    enum CodingKeys: String, CodingKey {
        case ticker, action, reasoning, date, status, outcome, currency
        case entryPrice = "entry_price", targetPrice = "target_price", stopLoss = "stop_loss"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ticker = c(.ticker, default: "")
        action = c(.action, default: "")
        entryPrice = c(.entryPrice)
        targetPrice = c(.targetPrice)
        stopLoss = c(.stopLoss)
        reasoning = c(.reasoning, default: "")
        date = c(.date, default: "")
        status = c(.status, default: "open")
        outcome = (c(.outcome) as JSONValue?).flatMap { $0 == .null ? nil : $0.display }
        currency = c(.currency, default: "EUR")
    }

    public var isOpen: Bool { status == "open" }

    /// Gleiche Regel wie das Web-Dashboard: buy/sell immer, watch mit Einstiegskurs,
    /// hold nur mit Stop (= Stop beim Broker nachziehen).
    public var isActionable: Bool {
        guard isOpen else { return false }
        switch action {
        case "buy", "sell": return true
        case "watch": return entryPrice != nil
        case "hold": return stopLoss != nil
        default: return false
        }
    }

    public var actionLabel: String {
        switch action {
        case "buy": "Kaufen"
        case "sell": "Verkaufen"
        case "watch": "Beobachten"
        case "hold": "Halten"
        default: action.capitalized
        }
    }

    public var statusLabel: String {
        switch status {
        case "open": "offen"
        case "executed": "ausgeführt"
        case "target_hit": "Ziel erreicht"
        case "stop_hit": "Stop ausgelöst"
        case "cancelled": "verworfen"
        default: status
        }
    }
}

public struct MandateRule: Decodable, Sendable, Identifiable, Hashable {
    public var id: String
    public var type: String
    public var value: Double?
    public var rule: String
    public var terms: [String]
    public var sector: String?

    enum CodingKeys: String, CodingKey { case id, type, value, rule, match, keywords, tickers, sector }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c(.id, default: UUID().uuidString)
        type = c(.type, default: "")
        value = c(.value)
        rule = c(.rule, default: "warn")
        terms = c(.match) ?? c(.keywords) ?? c(.tickers) ?? []
        sector = c(.sector)
    }

    /// Lesbare Beschreibung der Regel.
    public var label: String {
        let v = value.map { $0.formatted(.number.precision(.fractionLength(0...1))) } ?? "–"
        switch type {
        case "max_position_pct": return "Einzelposition höchstens \(v) %"
        case "min_cash_pct": return "Cash mindestens \(v) %"
        case "max_sector_pct": return "\(sector ?? "Sektor") höchstens \(v) %"
        case "max_keyword_pct": return "\(terms.prefix(3).joined(separator: "/")) höchstens \(v) %"
        case "forbidden_instrument": return "Verboten: \(terms.joined(separator: ", "))"
        case "forbidden_ticker": return terms.isEmpty ? "Keine gesperrten Ticker" : "Gesperrt: \(terms.joined(separator: ", "))"
        default: return id.replacingOccurrences(of: "_", with: " ")
        }
    }
}

public struct Mandate: Decodable, Sendable {
    public var version: Int?
    public var updatedAt: String?
    public var summary: String
    public var philosophy: String
    public var softPreferences: [String]
    public var taxDirectives: [String]
    public var horizonYears: Int?
    public var primaryGoal: String?
    public var monthlyContributionEur: Double?
    public var regionTargets: [String: Double]
    public var cashTargetPct: Double?
    public var hardRules: [MandateRule]
    public var singleTradeCapPct: Double?
    public var reviewCadence: String?

    enum CodingKeys: String, CodingKey {
        case version, philosophy, objective, targets
        case updatedAt = "updated_at", summary = "summary_human"
        case softPreferences = "soft_preferences", taxDirectives = "tax_directives"
        case hardRules = "hard_rules", singleTradeCapPct = "single_trade_cap_pct", reviewCadence = "review_cadence"
    }

    enum ObjectiveKeys: String, CodingKey {
        case horizonYears = "horizon_years", primaryGoal = "primary_goal"
        case monthlyContributionEur = "monthly_contribution_eur"
    }

    enum TargetKeys: String, CodingKey { case regions, cashPct = "cash_pct" }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        version = c(.version)
        updatedAt = c(.updatedAt)
        summary = c(.summary, default: "")
        philosophy = c(.philosophy, default: "")
        softPreferences = c(.softPreferences, default: [])
        taxDirectives = c(.taxDirectives, default: [])
        hardRules = c(.hardRules, default: [])
        singleTradeCapPct = c(.singleTradeCapPct)
        reviewCadence = c(.reviewCadence)
        let objective = try? c.nestedContainer(keyedBy: ObjectiveKeys.self, forKey: .objective)
        horizonYears = objective?(.horizonYears)
        primaryGoal = objective?(.primaryGoal)
        monthlyContributionEur = objective?(.monthlyContributionEur)
        let targets = try? c.nestedContainer(keyedBy: TargetKeys.self, forKey: .targets)
        regionTargets = targets?(.regions, default: [:]) ?? [:]
        cashTargetPct = targets?(.cashPct)
    }
}

public struct DriftDimension: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { "\(kind)|\(name)" }
    public var name: String
    public var kind: String
    public var target: Double?
    public var actual: Double?
    public var deviationPp: Double?
    public var severity: String

    enum CodingKeys: String, CodingKey {
        case name, kind, severity
        case target = "soll", actual = "ist", deviationPp = "abweichung_pp"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c(.name, default: "")
        kind = c(.kind, default: "")
        target = c(.target)
        actual = c(.actual)
        deviationPp = c(.deviationPp)
        severity = c(.severity, default: "ok")
    }
}

public struct StrategyDrift: Decodable, Sendable {
    public var dimensions: [DriftDimension]
    public var breaches: Int
    public var warnings: Int
    public var status: String

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        dimensions = c(.dimensions, default: [])
        breaches = c(.breaches, default: 0)
        warnings = c(.warnings, default: 0)
        status = c(.status, default: "ok")
    }

    enum CodingKeys: String, CodingKey { case dimensions, breaches, warnings, status }
}

public struct WeightedItem: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { name }
    public var name: String
    public var valueEur: Double?
    public var pct: Double

    enum CodingKeys: String, CodingKey { case name, pct, valueEur = "value_eur", weightPct = "weight_pct" }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c(.name, default: "")
        valueEur = c(.valueEur)
        pct = c(.pct) ?? c(.weightPct) ?? 0
    }
}

public struct Lookthrough: Decodable, Sendable {
    public var assetClass: [WeightedItem]
    public var topTitles: [WeightedItem]
    public var regions: [WeightedItem]
    public var sectors: [WeightedItem]
    public var fundCount: Int
    public var unresearchedFunds: Int

    enum CodingKeys: String, CodingKey {
        case regions, sectors
        case assetClass = "asset_class", topTitles = "top_titles"
        case fundCount = "fund_count", unresearchedFunds = "unresearched_funds"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        assetClass = c(.assetClass, default: [])
        topTitles = c(.topTitles, default: [])
        regions = c(.regions, default: [])
        sectors = c(.sectors, default: [])
        fundCount = c(.fundCount, default: 0)
        unresearchedFunds = c(.unresearchedFunds, default: 0)
    }
}

public struct FundResearch: Decodable, Sendable, Hashable {
    public var instrumentType: String?
    public var terPct: Double?
    public var summary: String?
    public var confidence: String?
    public var source: String?
    public var topHoldings: [WeightedItem]
    public var sectorBreakdown: [String: Double]
    public var regionBreakdown: [String: Double]
    public var researchedAt: String?

    enum CodingKeys: String, CodingKey {
        case summary, confidence, source
        case instrumentType = "instrument_type", terPct = "ter_pct", topHoldings = "top_holdings"
        case sectorBreakdown = "sector_breakdown", regionBreakdown = "region_breakdown"
        case researchedAt = "researched_at"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        instrumentType = c(.instrumentType)
        terPct = c(.terPct)
        summary = c(.summary)
        confidence = c(.confidence)
        source = c(.source)
        topHoldings = c(.topHoldings, default: [])
        sectorBreakdown = c(.sectorBreakdown, default: [:])
        regionBreakdown = c(.regionBreakdown, default: [:])
        researchedAt = c(.researchedAt)
    }
}

public struct Fund: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { isin.isEmpty ? ticker : isin }
    public var name: String
    public var isin: String
    public var ticker: String
    public var shares: Double?
    public var research: FundResearch?

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c(.name, default: "")
        isin = c(.isin, default: "")
        ticker = c(.ticker, default: "")
        shares = c(.shares)
        research = c(.research)
    }

    enum CodingKeys: String, CodingKey { case name, isin, ticker, shares, research }
}
