import Foundation

public struct MacroValue: Decodable, Sendable, Hashable {
    public var value: Double?
    public var date: String?
    public var description: String?
    public var note: String?

    enum CodingKeys: String, CodingKey { case value, date, description, note, timestamp }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        value = c(.value)
        date = c(.date) ?? c(.timestamp)
        description = c(.description)
        note = c(.note)
    }
}

public struct FearGreed: Decodable, Sendable, Hashable {
    public var value: Double?
    public var rating: String?
    public var previousClose: Double?
    public var previousWeek: Double?
    public var previousMonth: Double?
    public var previousYear: Double?

    enum CodingKeys: String, CodingKey {
        case value, rating
        case previousClose = "previous_close", previousWeek = "previous_1_week"
        case previousMonth = "previous_1_month", previousYear = "previous_1_year"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        value = c(.value)
        rating = c(.rating)
        previousClose = c(.previousClose)
        previousWeek = c(.previousWeek)
        previousMonth = c(.previousMonth)
        previousYear = c(.previousYear)
    }

    /// Deutsche Bezeichnung der CNN-Stufe.
    public var ratingLabel: String {
        switch rating?.lowercased() {
        case "extreme fear": "Extreme Angst"
        case "fear": "Angst"
        case "neutral": "Neutral"
        case "greed": "Gier"
        case "extreme greed": "Extreme Gier"
        default: rating ?? "–"
        }
    }
}

public struct MacroData: Decodable, Sendable {
    public var us: [String: MacroValue]
    public var eu: [String: MacroValue]
    public var fearGreed: FearGreed?
    public var collectedAt: String?

    enum CodingKeys: String, CodingKey { case us, eu, fearGreed = "fear_greed", collectedAt = "collected_at" }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        us = c(.us, default: [:])
        eu = c(.eu, default: [:])
        fearGreed = c(.fearGreed)
        collectedAt = c(.collectedAt)
    }

    /// Anzeigereihenfolge und Beschriftung der bekannten Kennzahlen.
    public static let usLabels: [(key: String, label: String, unit: String)] = [
        ("fed_funds_rate", "Leitzins Fed", "%"),
        ("us_10y_yield", "US-Rendite 10 J.", "%"),
        ("us_2y_yield", "US-Rendite 2 J.", "%"),
        ("yield_curve_spread", "Zinskurve 10 J. – 2 J.", "pp"),
        ("vix", "VIX", ""),
        ("credit_spread_hy", "High-Yield-Spread", "%"),
        ("us_unemployment", "Arbeitslosigkeit USA", "%"),
        ("us_gdp_growth", "BIP-Wachstum USA", "%"),
    ]

    public static let euLabels: [(key: String, label: String, unit: String)] = [
        ("eu_hicp_inflation", "Inflation Eurozone", "%"),
        ("eur_usd", "EUR/USD", ""),
    ]
}

public struct EarningsEvent: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { "\(ticker)|\(date)" }
    public var ticker: String
    public var name: String
    public var event: String
    public var date: String

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ticker = c(.ticker, default: "")
        name = c(.name, default: "")
        event = c(.event, default: "Earnings")
        date = c(.date, default: "")
    }

    enum CodingKeys: String, CodingKey { case ticker, name, event, date }
}

public struct MacroEvent: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { "\(name)|\(date)" }
    public var date: String
    public var name: String
    public var category: String?
    public var daysUntil: Int?

    enum CodingKeys: String, CodingKey { case date, name, category, daysUntil = "days_until" }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        date = c(.date, default: "")
        name = c(.name, default: "")
        category = c(.category)
        daysUntil = c(.daysUntil)
    }
}

public struct Holiday: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { "\(name)|\(date)" }
    public var date: String
    public var name: String
    public var exchanges: String?
    public var daysUntil: Int?

    enum CodingKeys: String, CodingKey { case date, name, exchanges, daysUntil = "days_until" }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        date = c(.date, default: "")
        name = c(.name, default: "")
        exchanges = c(.exchanges)
        daysUntil = c(.daysUntil)
    }
}

public struct MarketStatus: Decodable, Sendable, Hashable {
    public var nyseOpen: Bool
    public var xetraOpen: Bool
    public var wienOpen: Bool
    public var isWeekend: Bool
    public var upcomingHolidays: [Holiday]

    enum CodingKeys: String, CodingKey {
        case nyseOpen = "nyse_open", xetraOpen = "xetra_open", wienOpen = "wien_open"
        case isWeekend = "is_weekend", upcomingHolidays = "upcoming_holidays"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        nyseOpen = c.flag(.nyseOpen)
        xetraOpen = c.flag(.xetraOpen)
        wienOpen = c.flag(.wienOpen)
        isWeekend = c.flag(.isWeekend)
        upcomingHolidays = c(.upcomingHolidays, default: [])
    }
}

public struct CalendarData: Decodable, Sendable {
    public var earnings: [EarningsEvent]
    public var marketStatus: MarketStatus?
    public var macroEvents: [MacroEvent]

    enum CodingKeys: String, CodingKey {
        case earnings, marketStatus = "market_status", macroEvents = "macro_events"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        earnings = c(.earnings, default: [])
        marketStatus = c(.marketStatus)
        macroEvents = c(.macroEvents, default: [])
    }
}

public struct NewsItem: Decodable, Sendable, Identifiable, Hashable {
    public var id: String { url ?? title }
    public var title: String
    public var description: String?
    public var url: String?
    public var age: String?
    public var published: String?
    public var source: String?

    enum CodingKeys: String, CodingKey { case title, description, url, age, published, source }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        title = c(.title, default: "")
        description = c(.description)
        url = c(.url)
        age = c(.age)
        published = c(.published)
        source = c(.source)
    }

    public var link: URL? { url.flatMap(URL.init(string:)) }
    public var host: String? { link?.host()?.replacingOccurrences(of: "www.", with: "") }
}

public struct Sentiment: Decodable, Sendable, Hashable {
    public var bullish: Double?
    public var bearish: Double?
    public var neutral: Double?

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        bullish = c(.bullish)
        bearish = c(.bearish)
        neutral = c(.neutral)
    }

    enum CodingKeys: String, CodingKey { case bullish, bearish, neutral }
}

public struct NewsData: Decodable, Sendable {
    public var positionNews: [String: [NewsItem]]
    public var bloombergHeadlines: [NewsItem]
    public var macroNews: [NewsItem]
    public var opportunities: [NewsItem]
    public var sentiment: [String: Sentiment]

    enum CodingKeys: String, CodingKey {
        case sentiment, opportunities
        case positionNews = "position_news", bloombergHeadlines = "bloomberg_headlines", macroNews = "macro_news"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        positionNews = c(.positionNews, default: [:])
        bloombergHeadlines = c(.bloombergHeadlines, default: [])
        macroNews = c(.macroNews, default: [])
        opportunities = c(.opportunities, default: [])
        sentiment = c(.sentiment, default: [:])
    }
}
