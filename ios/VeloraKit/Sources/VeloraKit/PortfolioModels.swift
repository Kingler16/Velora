import Foundation

public struct Position: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { "\(account)|\(ticker)" }
    public var name: String
    public var ticker: String
    public var isin: String?
    public var account: String
    public var shares: Double
    public var buyIn: Double?
    public var buyInEur: Double?
    /// Währung, in der der Buy-in erfasst ist – nicht zwingend die des Kurses.
    public var currency: String
    /// Währung, in der `currentPrice` und die 52-Wochen-Spanne notieren.
    public var quoteCurrency: String
    public var currentPrice: Double?
    public var currentPriceEur: Double?
    public var currentValueEur: Double
    public var investedEur: Double?
    public var pnlEur: Double?
    public var pnlPct: Double?
    public var hasLivePrice: Bool
    public var sector: String?
    public var beta: Double?
    public var peRatio: Double?
    public var dividendYield: Double?
    public var changePct: Double?
    public var perf1mPct: Double?
    public var perf6mPct: Double?
    public var perf1yPct: Double?
    public var high52w: Double?
    public var low52w: Double?
    public var allocationPct: Double?

    enum CodingKeys: String, CodingKey {
        case name, ticker, isin, account, shares, currency, sector, beta
        case buyIn = "buy_in", buyInEur = "buy_in_eur", quoteCurrency = "quote_currency"
        case currentPrice = "current_price", currentPriceEur = "current_price_eur"
        case currentValueEur = "current_value_eur", investedEur = "invested_eur"
        case pnlEur = "pnl_eur", pnlPct = "pnl_pct", hasLivePrice = "has_live_price"
        case peRatio = "pe_ratio", dividendYield = "dividend_yield", changePct = "change_pct"
        case perf1mPct = "perf_1m_pct", perf6mPct = "perf_6m_pct", perf1yPct = "perf_1y_pct"
        case high52w = "high_52w", low52w = "low_52w", allocationPct = "allocation_pct"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c(.name, default: "")
        ticker = c(.ticker, default: "")
        isin = c(.isin)
        account = c(.account, default: "")
        shares = c(.shares, default: 0)
        buyIn = c(.buyIn)
        buyInEur = c(.buyInEur)
        currency = Format.currencyCode(c(.currency, default: "EUR"))
        // Ältere Server liefern keine Notierungswährung.
        quoteCurrency = Format.currencyCode(c(.quoteCurrency, default: currency))
        currentPrice = c(.currentPrice)
        currentPriceEur = c(.currentPriceEur)
        currentValueEur = c(.currentValueEur, default: 0)
        investedEur = c(.investedEur)
        pnlEur = c(.pnlEur)
        pnlPct = c(.pnlPct)
        hasLivePrice = c.flag(.hasLivePrice)
        sector = c(.sector)
        beta = c(.beta)
        peRatio = c(.peRatio)
        dividendYield = c(.dividendYield)
        changePct = c(.changePct)
        perf1mPct = c(.perf1mPct)
        perf6mPct = c(.perf6mPct)
        perf1yPct = c(.perf1yPct)
        high52w = c(.high52w)
        low52w = c(.low52w)
        allocationPct = c(.allocationPct)
    }

    public var displayName: String { name.isEmpty ? ticker : name }
}

public struct BankAccount: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { name }
    /// Schlüssel des Kontos (z. B. `comdirect_giro`), dient den Edit-Endpoints als `key`.
    public var name: String
    public var bank: String
    public var value: Double
    public var interest: Double
    public var note: String
    public var isDepotCash: Bool

    enum CodingKeys: String, CodingKey {
        case name, bank, value, interest, note
        case isDepotCash = "is_depot_cash"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c(.name, default: "")
        bank = c(.bank, default: "")
        value = c(.value, default: 0)
        interest = c(.interest, default: 0)
        note = c(.note, default: "")
        isDepotCash = c.flag(.isDepotCash)
    }
}

public struct AccountGroup: Decodable, Sendable, Hashable {
    public var displayName: String
    public var positions: [Position]
    public var totalValue: Double
    public var totalPnl: Double

    enum CodingKeys: String, CodingKey {
        case positions
        case displayName = "display_name", totalValue = "total_value", totalPnl = "total_pnl"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        displayName = c(.displayName, default: "")
        positions = c(.positions, default: [])
        totalValue = c(.totalValue, default: 0)
        totalPnl = c(.totalPnl, default: 0)
    }
}

public struct PortfolioOverview: Decodable, Sendable {
    public var totalValueEur: Double
    public var holdingsValueEur: Double
    public var cashTotal: Double
    public var depotCash: Double?
    public var freeCash: Double?
    public var totalInvestedEur: Double
    public var totalPnlEur: Double
    public var totalPnlPct: Double
    public var positionCount: Int
    public var cashPct: Double?
    public var positions: [Position]
    public var bankAccounts: [BankAccount]
    public var eurUsdRate: Double?
    public var regionExposure: [String: Double]
    public var sectorBreakdown: [String: Double]
    public var accountsGrouped: [String: AccountGroup]

    enum CodingKeys: String, CodingKey {
        case positions
        case totalValueEur = "total_value_eur", holdingsValueEur = "holdings_value_eur"
        case cashTotal = "cash_total", depotCash = "depot_cash", freeCash = "free_cash"
        case totalInvestedEur = "total_invested_eur", totalPnlEur = "total_pnl_eur"
        case totalPnlPct = "total_pnl_pct", positionCount = "position_count", cashPct = "cash_pct"
        case bankAccounts = "bank_accounts", eurUsdRate = "eur_usd_rate"
        case regionExposure = "region_exposure", sectorBreakdown = "sector_breakdown"
        case accountsGrouped = "accounts_grouped"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        totalValueEur = c(.totalValueEur, default: 0)
        holdingsValueEur = c(.holdingsValueEur, default: 0)
        cashTotal = c(.cashTotal, default: 0)
        depotCash = c(.depotCash)
        freeCash = c(.freeCash)
        totalInvestedEur = c(.totalInvestedEur, default: 0)
        totalPnlEur = c(.totalPnlEur, default: 0)
        totalPnlPct = c(.totalPnlPct, default: 0)
        positionCount = c(.positionCount, default: 0)
        cashPct = c(.cashPct)
        positions = c(.positions, default: [])
        bankAccounts = c(.bankAccounts, default: [])
        eurUsdRate = c(.eurUsdRate)
        regionExposure = c(.regionExposure, default: [:])
        sectorBreakdown = c(.sectorBreakdown, default: [:])
        accountsGrouped = c(.accountsGrouped, default: [:])
    }

    /// Tagesveränderung des Depots in EUR, hochgerechnet aus den Tagesänderungen der Positionen.
    public var dayChangeEur: Double {
        positions.reduce(0) { sum, p in
            guard let pct = p.changePct, pct > -100 else { return sum }
            return sum + p.currentValueEur - p.currentValueEur / (1 + pct / 100)
        }
    }

    /// Depots sortiert nach Wert, mit dem Schlüssel (für API-Aufrufe) und Anzeigenamen.
    public var sortedAccounts: [(key: String, group: AccountGroup)] {
        accountsGrouped.map { ($0.key, $0.value) }.sorted { $0.group.totalValue > $1.group.totalValue }
    }
}

public struct Snapshot: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { month }
    public var month: String
    public var totalValue: Double
    public var totalPnlEur: Double?
    public var totalPnlPct: Double?
    public var note: String?

    enum CodingKeys: String, CodingKey {
        case month, note
        case totalValue = "total_value", totalPnlEur = "total_pnl_eur", totalPnlPct = "total_pnl_pct"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        month = c(.month, default: "")
        totalValue = c(.totalValue, default: 0)
        totalPnlEur = c(.totalPnlEur)
        totalPnlPct = c(.totalPnlPct)
        note = c(.note)
    }

    /// Erster Tag des Monats (`2024-11` → 1.11.2024).
    public var date: Date? { VeloraDate.parse(month + "-01") }
}

public struct Benchmark: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { name }
    public var name: String
    public var changePct: Double?

    enum CodingKeys: String, CodingKey { case name, changePct = "change_pct" }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c(.name, default: "")
        changePct = c(.changePct)
    }
}

public struct IndexQuote: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { name }
    public var name: String
    public var description: String
    public var value: Double?
    public var changePct: Double?

    enum CodingKeys: String, CodingKey { case name, description, value, changePct = "change_pct" }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c(.name, default: "")
        description = c(.description, default: "")
        value = c(.value)
        changePct = c(.changePct)
    }
}

public struct CacheEntry: Decodable, Sendable, Hashable {
    public var available: Bool
    public var ageMinutes: Double?
    public var timestamp: String?

    enum CodingKeys: String, CodingKey { case available, timestamp, ageMinutes = "age_minutes" }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        available = c.flag(.available)
        ageMinutes = c(.ageMinutes)
        timestamp = c(.timestamp)
    }
}

public struct ServerStatus: Decodable, Sendable, Hashable {
    public var cache: [String: CacheEntry]
    public var refreshRunning: Bool

    enum CodingKeys: String, CodingKey { case cache, refreshRunning = "refresh_running" }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        cache = c(.cache, default: [:])
        refreshRunning = c.flag(.refreshRunning)
    }

    public var market: CacheEntry? { cache["market_data"] }
}

public struct TaxLossItem: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { "\(account)|\(ticker)" }
    public var name: String
    public var ticker: String
    public var pnlEur: Double
    public var pnlPct: Double?
    public var account: String

    enum CodingKeys: String, CodingKey { case name, ticker, account, pnlEur = "pnl_eur", pnlPct = "pnl_pct" }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c(.name, default: "")
        ticker = c(.ticker, default: "")
        pnlEur = c(.pnlEur, default: 0)
        pnlPct = c(.pnlPct)
        account = c(.account, default: "")
    }
}

public struct TaxLossSummary: Decodable, Sendable, Hashable {
    public var totalGains: Double
    public var totalLosses: Double
    public var potentialTax: Double
    public var netTax: Double
    public var taxSavings: Double
    public var gains: [TaxLossItem]
    public var losses: [TaxLossItem]

    enum CodingKeys: String, CodingKey {
        case gains, losses
        case totalGains = "total_gains", totalLosses = "total_losses"
        case potentialTax = "potential_tax", netTax = "net_tax", taxSavings = "tax_savings"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        totalGains = c(.totalGains, default: 0)
        totalLosses = c(.totalLosses, default: 0)
        potentialTax = c(.potentialTax, default: 0)
        netTax = c(.netTax, default: 0)
        taxSavings = c(.taxSavings, default: 0)
        gains = c(.gains, default: [])
        losses = c(.losses, default: [])
    }
}

public struct TaxLoss: Decodable, Sendable {
    public var taxRate: Double
    public var total: TaxLossSummary
    public var perAccount: [String: TaxLossSummary]

    enum CodingKeys: String, CodingKey { case taxRate = "tax_rate", perAccount = "per_account" }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        taxRate = c(.taxRate, default: 0.275)
        total = try TaxLossSummary(from: decoder)
        perAccount = c(.perAccount, default: [:])
    }
}

public struct StopPosition: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { "\(account)|\(ticker)" }
    public var ticker: String
    public var name: String
    public var account: String
    public var status: String
    /// Gesetzter Stop in Notierungswährung (dafür rechnet der Server Abstand und Risiko).
    public var currentStop: Double?
    /// Gesetzter Stop so, wie er beim Broker steht (Währung in `stopCurrency`).
    public var brokerStop: Double?
    public var stopCurrency: String?
    public var stopSetAt: String?
    public var targetStop: Double?
    public var currentPrice: Double?
    public var currency: String
    public var shares: Double?
    public var distancePct: Double?
    public var targetDistancePct: Double?
    public var valueEur: Double?
    public var riskEur: Double?
    public var riskTargetEur: Double?
    public var currentPriceEur: Double?
    public var currentStopEur: Double?
    public var targetStopEur: Double?
    public var hint: String?

    enum CodingKeys: String, CodingKey {
        case ticker, name, account, status, currency, shares
        case currentStop = "ist_stop", brokerStop = "ist_stop_broker", stopCurrency = "stop_currency"
        case stopSetAt = "stop_set_at"
        case targetStop = "soll_stop", currentPrice = "current_price"
        case distancePct = "abstand_pct", targetDistancePct = "soll_abstand_pct"
        case valueEur = "wert_eur", riskEur = "risiko_eur", riskTargetEur = "risiko_soll_eur"
        case currentPriceEur = "current_price_eur", currentStopEur = "ist_stop_eur", targetStopEur = "soll_stop_eur"
        case hint = "hinweis"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ticker = c(.ticker, default: "")
        name = c(.name, default: "")
        account = c(.account, default: "")
        status = c(.status, default: "")
        currentStop = c(.currentStop)
        // Ältere Server kennen nur den Stop in Notierungswährung.
        brokerStop = c(.brokerStop) ?? currentStop
        stopCurrency = (c(.stopCurrency) as String?).map(Format.currencyCode)
        stopSetAt = c(.stopSetAt)
        targetStop = c(.targetStop)
        currentPrice = c(.currentPrice)
        currency = Format.currencyCode(c(.currency, default: "EUR"))
        shares = c(.shares)
        distancePct = c(.distancePct)
        targetDistancePct = c(.targetDistancePct)
        valueEur = c(.valueEur)
        riskEur = c(.riskEur)
        riskTargetEur = c(.riskTargetEur)
        currentPriceEur = c(.currentPriceEur)
        currentStopEur = c(.currentStopEur)
        targetStopEur = c(.targetStopEur)
        hint = c(.hint)
    }

    public var displayName: String { name.isEmpty ? ticker : name }

    /// Währung, in der der Stop beim Broker steht.
    public var brokerCurrency: String { stopCurrency ?? currency }

    /// Weicht die Broker-Währung von der Notierung ab (z. B. EUR-Stop auf US-Aktie)?
    public var stopInOtherCurrency: Bool { brokerStop != nil && brokerCurrency != currency }

    /// Status, bei dem der Nutzer etwas am Stop tun sollte.
    public var needsAttention: Bool { ["kein_stop", "ungueltig", "zu_eng", "zu_weit", "nachziehbar"].contains(status) }

    /// Kann man für diese Position überhaupt einen Stop sinnvoll setzen?
    public var isStoppable: Bool { !["nicht_bewertbar", "kein_stop_noetig"].contains(status) || brokerStop != nil }
}

public struct StopOverview: Decodable, Sendable {
    public var positions: [StopPosition]
    public var withoutStop: Int
    public var withStop: Int
    public var totalRiskEur: Double
    public var unprotectedEur: Double

    enum CodingKeys: String, CodingKey {
        case positions
        case withoutStop = "ohne_stop", withStop = "mit_stop"
        case totalRiskEur = "risiko_eur_gesamt", unprotectedEur = "ungesichert_eur"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        positions = c(.positions, default: [])
        withoutStop = c(.withoutStop, default: 0)
        withStop = c(.withStop, default: 0)
        totalRiskEur = c(.totalRiskEur, default: 0)
        unprotectedEur = c(.unprotectedEur, default: 0)
    }
}

public struct Order: Decodable, Sendable, Identifiable, Hashable {
    public var id: String
    public var ticker: String
    public var action: String
    public var shares: Double
    public var limitPrice: Double?
    public var currency: String
    public var account: String
    public var placedDate: String?
    public var validUntil: String?
    public var note: String?

    enum CodingKeys: String, CodingKey {
        case id, ticker, action, shares, currency, account, note
        case limitPrice = "limit_price", placedDate = "placed_date", validUntil = "valid_until"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c(.id, default: UUID().uuidString)
        ticker = c(.ticker, default: "")
        action = c(.action, default: "")
        shares = c(.shares, default: 0)
        limitPrice = c(.limitPrice)
        currency = Format.currencyCode(c(.currency, default: "EUR"))
        account = c(.account, default: "")
        placedDate = c(.placedDate)
        validUntil = c(.validUntil)
        note = c(.note)
    }

    public var volume: Double? { limitPrice.map { $0 * shares } }

    /// Gültigkeit abgelaufen – beim Broker vermutlich schon gestrichen.
    public func isExpired(now: Date = .now) -> Bool {
        guard let until = VeloraDate.parse(validUntil) else { return false }
        return Calendar.current.startOfDay(for: now) > until
    }
}
