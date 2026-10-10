import Foundation

/// Antworten der `/api/app/*`-Endpoints – je Bildschirm eine.

public struct DashboardData: Decodable, Sendable {
    public var overview: PortfolioOverview
    public var indices: [IndexQuote]
    public var snapshots: [Snapshot]
    public var benchmarks: [Benchmark]
    public var actionable: [Recommendation]
    public var latestBriefing: Briefing?
    public var eurUsd: Double?
    public var status: ServerStatus?

    enum CodingKeys: String, CodingKey {
        case overview, indices, snapshots, benchmarks, actionable, status
        case latestBriefing = "latest_briefing", eurUsd = "eur_usd"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        overview = try c.decode(PortfolioOverview.self, forKey: .overview)
        indices = c(.indices, default: [])
        snapshots = c(.snapshots, default: [])
        benchmarks = c(.benchmarks, default: [])
        actionable = c(.actionable, default: [])
        latestBriefing = c(.latestBriefing)
        eurUsd = c(.eurUsd)
        status = c(.status)
    }
}

public struct PortfolioData: Decodable, Sendable {
    public var overview: PortfolioOverview
    public var snapshots: [Snapshot]
    public var benchmarks: [Benchmark]
    public var taxLoss: TaxLoss?
    public var kestMode: String
    public var defaultCurrency: String
    public var stops: StopOverview?
    public var stopLabels: [String: String]
    public var openOrders: [Order]
    public var accounts: [String]
    public var eurUsd: Double?
    public var status: ServerStatus?

    enum CodingKeys: String, CodingKey {
        case overview, snapshots, benchmarks, stops, accounts, status
        case taxLoss = "tax_loss", kestMode = "kest_mode", defaultCurrency = "default_currency"
        case stopLabels = "stop_labels", openOrders = "open_orders", eurUsd = "eur_usd"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        overview = try c.decode(PortfolioOverview.self, forKey: .overview)
        snapshots = c(.snapshots, default: [])
        benchmarks = c(.benchmarks, default: [])
        taxLoss = c(.taxLoss)
        kestMode = c(.kestMode, default: "per_account")
        defaultCurrency = c(.defaultCurrency, default: "EUR")
        stops = c(.stops)
        stopLabels = c(.stopLabels, default: [:])
        openOrders = c(.openOrders, default: [])
        accounts = c(.accounts, default: [])
        eurUsd = c(.eurUsd)
        status = c(.status)
    }

    public func stop(for position: Position) -> StopPosition? {
        stops?.positions.first { $0.ticker == position.ticker && $0.account == position.account }
    }

    /// Beim Broker liegende Stop-Orders (eine je Position mit gesetztem Stop), grösste zuerst.
    public var stopOrders: [StopPosition] {
        (stops?.positions ?? []).filter { $0.brokerStop != nil }.sorted { ($0.valueEur ?? 0) > ($1.valueEur ?? 0) }
    }

    /// Alles, was beim Broker offen ist: Stop-Orders plus Limit-Orders.
    public var openOrderCount: Int { stopOrders.count + openOrders.count }

    public func stopLabel(_ status: String) -> String { stopLabels[status] ?? status }
}

public struct MarketData: Decodable, Sendable {
    public var indices: [IndexQuote]
    public var macro: MacroData?
    public var calendar: CalendarData?
    public var sectorHeatmap: [String: Double]
    public var news: NewsData?
    public var status: ServerStatus?

    enum CodingKeys: String, CodingKey {
        case indices, macro, calendar, news, status
        case sectorHeatmap = "sector_heatmap"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        indices = c(.indices, default: [])
        macro = c(.macro)
        calendar = c(.calendar)
        sectorHeatmap = c(.sectorHeatmap, default: [:])
        news = c(.news)
        status = c(.status)
    }
}

public struct BriefingsData: Decodable, Sendable {
    public var briefings: [Briefing]
    public var notes: Notes?

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        briefings = c(.briefings, default: [])
        notes = c(.notes)
    }

    enum CodingKeys: String, CodingKey { case briefings, notes }
}

public struct RecommendationsData: Decodable, Sendable {
    public var recommendations: [Recommendation]
    public var actionableCount: Int
    public var eurUsd: Double?
    public var openOrders: [Order]
    public var accounts: [String]
    public var theses: [String: Thesis]

    enum CodingKeys: String, CodingKey {
        case recommendations, accounts, theses
        case actionableCount = "actionable_count", eurUsd = "eur_usd", openOrders = "open_orders"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        recommendations = c(.recommendations, default: [])
        actionableCount = c(.actionableCount, default: 0)
        eurUsd = c(.eurUsd)
        openOrders = c(.openOrders, default: [])
        accounts = c(.accounts, default: [])
        theses = c(.theses, default: [:])
    }
}

public struct StrategyData: Decodable, Sendable {
    public var mandate: Mandate?
    public var drift: StrategyDrift?

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mandate = c(.mandate)
        drift = c(.drift)
    }

    enum CodingKeys: String, CodingKey { case mandate, drift }
}

public struct HoldingsData: Decodable, Sendable {
    public var funds: [Fund]
    public var lookthrough: Lookthrough?
    public var researchRunning: Bool

    enum CodingKeys: String, CodingKey { case funds, lookthrough, researchRunning = "research_running" }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        funds = c(.funds, default: [])
        lookthrough = c(.lookthrough)
        researchRunning = c.flag(.researchRunning)
    }
}

public struct SystemVersion: Decodable, Sendable {
    public var available: Bool
    public var shortSha: String?
    public var subject: String?
    public var date: String?

    enum CodingKeys: String, CodingKey { case available, subject, date, shortSha = "short_sha" }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        available = c.flag(.available)
        shortSha = c(.shortSha)
        subject = c(.subject)
        date = c(.date)
    }
}

public struct ServerSettings: Decodable, Sendable {
    public var briefingDays: [String]
    public var briefingTime: String?
    public var language: String?
    public var kestMode: String?
    public var defaultCurrency: String?
    public var taxRegime: String?

    enum CodingKeys: String, CodingKey { case schedule, user }
    enum ScheduleKeys: String, CodingKey { case briefingDays = "briefing_days", briefingTime = "briefing_time" }
    enum UserKeys: String, CodingKey {
        case language, kestMode = "kest_mode", defaultCurrency = "default_currency", taxRegime = "tax_regime"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let s = try? c.nestedContainer(keyedBy: ScheduleKeys.self, forKey: .schedule)
        briefingDays = s?(.briefingDays, default: []) ?? []
        briefingTime = s?(.briefingTime)
        let u = try? c.nestedContainer(keyedBy: UserKeys.self, forKey: .user)
        language = u?(.language)
        kestMode = u?(.kestMode)
        defaultCurrency = u?(.defaultCurrency)
        taxRegime = u?(.taxRegime)
    }
}

/// Antwort der Schreib-Endpoints: `{"status": "ok", "message": …}` bzw. `{"error": …}`.
public struct ActionResult: Decodable, Sendable {
    public var status: String?
    public var message: String?

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = c(.status)
        message = c(.message)
    }

    enum CodingKeys: String, CodingKey { case status, message }
}
