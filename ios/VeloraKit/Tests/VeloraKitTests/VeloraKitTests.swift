import Foundation
import Testing
@testable import VeloraKit

/// Fixtures sind synthetisch (keine echten Depotdaten), bilden aber die Form der Server-Antworten nach.
private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
    try JSONDecoder().decode(T.self, from: Data(json.utf8))
}

@Suite struct DecodingTests {
    @Test func dashboardWithSnakeCaseAccountKeys() throws {
        let data = try decode(DashboardData.self, """
        {"overview": {"total_value_eur": 1000, "holdings_value_eur": 800, "cash_total": 200,
          "total_invested_eur": 700, "total_pnl_eur": 100, "total_pnl_pct": 14.3, "position_count": 1,
          "positions": [{"name": "Test AG", "ticker": "TST.DE", "account": "scalable_capital", "shares": 10,
                         "current_value_eur": 800, "change_pct": 1.5, "has_live_price": true, "perf_1m_pct": 2.0, "high_52w": 90}],
          "bank_accounts": [{"name": "giro", "bank": "Bank", "value": 200, "is_depot_cash": false}],
          "accounts_grouped": {"scalable_capital": {"display_name": "Scalable Capital", "positions": [], "total_value": 800, "total_pnl": 100}}},
         "indices": [{"name": "DAX", "description": "DE", "value": 24000, "change_pct": -0.5}],
         "snapshots": [{"month": "2024-11", "total_value": 900}],
         "benchmarks": [], "actionable": [{"ticker": "TST.DE", "action": "watch", "entry_price": 70, "status": "open", "date": "2026-03-08T08:30:00.000000"}],
         "latest_briefing": null,
         "status": {"cache": {"market_data": {"available": true, "age_minutes": 12.5, "timestamp": "21.05.2026 18:23"}}, "refresh_running": false}}
        """)
        // Kontoschlüssel müssen unverändert bleiben – sie gehen so an die Edit-Endpoints zurück.
        #expect(data.overview.accountsGrouped.keys.first == "scalable_capital")
        #expect(data.overview.positions.first?.perf1mPct == 2.0)
        #expect(data.overview.positions.first?.high52w == 90)
        #expect(data.overview.positions.first?.hasLivePrice == true)
        #expect(data.actionable.first?.isActionable == true)
        #expect(data.status?.market?.ageMinutes == 12.5)
        #expect(data.snapshots.first?.date != nil)
        #expect(data.latestBriefing == nil)
    }

    @Test func missingAndNullFieldsFallBack() throws {
        let p = try decode(Position.self, #"{"ticker": "X", "pnl_pct": null, "shares": 3}"#)
        #expect(p.displayName == "X")
        #expect(p.pnlPct == nil)
        #expect(p.currency == "EUR")
    }

    @Test func taxLossTopLevelAndPerAccount() throws {
        let t = try decode(TaxLoss.self, """
        {"tax_rate": 0.275, "total_gains": 10, "total_losses": -5, "potential_tax": 2.75, "net_tax": 1.38, "tax_savings": 1.37,
         "gains": [{"name": "A", "ticker": "A", "pnl_eur": 10, "account": "x_y"}], "losses": [],
         "per_account": {"x_y": {"total_gains": 10, "gains": [], "losses": []}}}
        """)
        #expect(t.total.totalGains == 10)
        #expect(t.perAccount["x_y"]?.totalGains == 10)
    }

    @Test func mandateNestedObjects() throws {
        let m = try decode(Mandate.self, """
        {"summary_human": "S", "objective": {"horizon_years": 25, "monthly_contribution_eur": 300},
         "targets": {"regions": {"USA": 55}, "cash_pct": 8},
         "hard_rules": [{"id": "max_single_stock", "type": "max_position_pct", "value": 12, "exceptions": {}, "rule": "block"},
                        {"id": "no_leverage", "type": "forbidden_instrument", "match": ["hebel", "cfd"], "rule": "block"}]}
        """)
        #expect(m.horizonYears == 25)
        #expect(m.regionTargets["USA"] == 55)
        #expect(m.cashTargetPct == 8)
        #expect(m.hardRules[0].label == "Einzelposition höchstens 12 %")
        #expect(m.hardRules[1].terms == ["hebel", "cfd"])
    }

    @Test func chatMessagesWithToolUseAndIntFlags() throws {
        let d = try decode(ThreadDetail.self, """
        {"thread": {"id": "t1", "title": "Test", "message_count": 2, "is_pinned": 0},
         "messages": [{"id": 1, "role": "user", "content": "Hallo"},
                      {"id": 2, "role": "tool_use", "content": "{\\"id\\": \\"x\\", \\"name\\": \\"mcp__velora__update_watchlist\\", \\"input\\": {\\"ticker\\": \\"RKLB\\"}}"}]}
        """)
        #expect(d.thread.isPinned == false)
        #expect(d.messages[0].id == "1")
        #expect(d.messages[1].tool?.label == "Update watchlist")
        #expect(d.messages[1].tool?.input["ticker"] == "RKLB")
    }

    @Test func notesAcceptMixedInsights() throws {
        let n = try decode(Notes.self, #"{"key_insights": ["a", {"insight": "b"}], "position_theses": {"V": {"thesis": "t"}}}"#)
        #expect(n.keyInsights == ["a", "b"])
        #expect(n.positionTheses["V"]?.thesis == "t")
    }
}

@Suite struct SSETests {
    @Test func parsesVeloraChatStream() {
        let raw = """
        event: start
        data: {"thread_id": "t1"}

        event: token
        data: {"text": "Hallo "}

        event: token
        data: {"text": "Welt"}

        event: confirmation_required
        data: {"action_id": "a1", "summary": "RKLB auf Watchlist", "tool_name": "mcp__velora__update_watchlist", "params": {"ticker": "RKLB"}}

        event: done
        data: {"session_id": "s"}


        """
        var parser = SSEParser()
        var events: [ChatStreamEvent] = []
        for line in raw.split(separator: "\n", omittingEmptySubsequences: false) {
            if let e = parser.feed(String(line)), let chat = SSEParser.chatEvent(event: e.event, data: e.data) {
                events.append(chat)
            }
        }
        var text = ""
        var confirmation: PendingConfirmation?
        var done = false
        for e in events {
            switch e {
            case .token(let t): text += t
            case .confirmationRequired(let c): confirmation = c
            case .done: done = true
            default: break
            }
        }
        #expect(text == "Hallo Welt")
        #expect(confirmation?.actionId == "a1")
        #expect(confirmation?.params["ticker"] == "RKLB")
        #expect(done)
    }
}

@Suite struct FormatTests {
    @Test func dates() {
        #expect(VeloraDate.parse("2026-03-08T08:30:00.000000") != nil)
        #expect(VeloraDate.parse("2026-05-28") != nil)
        #expect(VeloraDate.parse("2026-08-31T21:18:16+02:00") != nil)
        #expect(VeloraDate.parse("Thu, 21 May 2026 16:16:11 GMT") != nil)
        #expect(VeloraDate.parse("") == nil)
    }

    @Test func numbersAreAustrian() {
        #expect(Format.pct(19.5).contains("19,5"))
        #expect(Format.pct(19.5).hasPrefix("+"))
        #expect(Format.eur(56151).contains("56.151,00"))
        #expect(Format.signedEur(-12.5).contains("12,50"))
        #expect(Format.signedEur(-12.5).hasPrefix("−") || Format.signedEur(-12.5).hasPrefix("-"))
        #expect(Format.accountName("scalable_capital") == "Scalable Capital")
    }

    @Test func endpointNormalisation() {
        #expect(ServerEndpoints.url(from: "rockpi:8080/")?.absoluteString == "http://rockpi:8080")
        #expect(ServerEndpoints.url(from: "100.69.43.83")?.absoluteString == "http://100.69.43.83:8080")
        #expect(ServerEndpoints.url(from: "http://rockpi-4c.tail7cebc3.ts.net")?.absoluteString == "http://rockpi-4c.tail7cebc3.ts.net:8080")
        #expect(ServerEndpoints.url(from: "https://velora.example.org")?.absoluteString == "https://velora.example.org")
        #expect(ServerEndpoints.url(from: "  ") == nil)
        let e = ServerEndpoints(lan: "192.168.1.27:8080", remote: "")
        #expect(e.candidates.count == 1)
    }

    @Test func dayChange() throws {
        let o = try decode(PortfolioOverview.self, #"{"positions": [{"ticker": "A", "current_value_eur": 110, "change_pct": 10}]}"#)
        #expect(abs(o.dayChangeEur - 10) < 0.001)
    }
}

/// Prüft echte Server-Antworten, wenn `VELORA_API_DUMP` auf einen Ordner mit
/// `dashboard.json`, `portfolio.json` … zeigt (nicht eingecheckt – private Daten).
@Suite struct RealResponseTests {
    static let dir = ProcessInfo.processInfo.environment["VELORA_API_DUMP"].map(URL.init(fileURLWithPath:))

    private func load<T: Decodable>(_ type: T.Type, _ name: String) throws -> T {
        try JSONDecoder().decode(T.self, from: Data(contentsOf: Self.dir!.appending(path: name + ".json")))
    }

    @Test(.enabled(if: dir != nil)) func allScreensDecode() throws {
        let dashboard = try load(DashboardData.self, "dashboard")
        #expect(!dashboard.overview.positions.isEmpty)
        let portfolio = try load(PortfolioData.self, "portfolio")
        #expect(portfolio.taxLoss != nil)
        #expect(portfolio.stops != nil)
        let market = try load(MarketData.self, "market")
        #expect(market.macro?.fearGreed?.value != nil)
        #expect(!(market.news?.bloombergHeadlines.isEmpty ?? true))
        let briefings = try load(BriefingsData.self, "briefings")
        #expect(!briefings.briefings.isEmpty)
        #expect(briefings.briefings.allSatisfy { $0.parsedDate != nil })
        for briefing in briefings.briefings where briefing.hasFullText {
            let doc = BriefingDocument.parse(briefing.fullText ?? "")
            #expect(doc.sections.count >= 5, "\(briefing.date): nur \(doc.sections.count) Abschnitte")
            let text = doc.sections.flatMap(\.blocks).map { InlineRun.plainText($0.runs) }.joined()
                + doc.sections.map(\.title).joined()
            #expect(!text.contains("<b>") && !text.contains("</") && !text.contains("&amp;"), "\(briefing.date): Rest-HTML")
            #expect(doc.sections.contains { $0.kind == .recommendations }, "\(briefing.date): Empfehlungen fehlen")
        }
        let recs = try load(RecommendationsData.self, "recommendations")
        #expect(!recs.recommendations.isEmpty)
        let strategy = try load(StrategyData.self, "strategy")
        #expect(strategy.mandate?.hardRules.isEmpty == false)
        let holdings = try load(HoldingsData.self, "holdings")
        #expect(holdings.funds.allSatisfy { $0.research != nil })
    }
}

@Suite struct PendingTests {
    @Test func pendingListUsesRowID() throws {
        struct Pending: Decodable { var pending: [PendingConfirmation] }
        let p = try JSONDecoder().decode(Pending.self, from: Data(#"{"pending": [{"id": "a9", "tool_name": "x", "params": {"ticker": "V"}, "summary": "S", "status": "pending"}]}"#.utf8))
        #expect(p.pending.first?.actionId == "a9")
    }
}

/// Antwortet lokal statt über das Netz; zählt die Verbindungsproben.
final class StubProtocol: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var probes = 0
    nonisolated(unsafe) static var reachableHosts: Set<String> = []
    private static let lock = NSLock()

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let url = request.url!
        if url.path().hasSuffix("refresh/status") { Self.lock.withLock { Self.probes += 1 } }
        DispatchQueue.global().asyncAfter(deadline: .now() + 0.2) { [self] in
            guard Self.reachableHosts.contains(url.host() ?? "") else {
                client?.urlProtocol(self, didFailWithError: URLError(.cannotConnectToHost))
                return
            }
            let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data(#"{"running": false}"#.utf8))
            client?.urlProtocolDidFinishLoading(self)
        }
    }

    override func stopLoading() {}
}

@Suite(.serialized) struct ClientTests {
    struct Status: Decodable { var running: Bool }

    private func client() -> VeloraClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubProtocol.self]
        StubProtocol.probes = 0
        StubProtocol.reachableHosts = ["100.69.43.83"]
        return VeloraClient(endpoints: ServerEndpoints(lan: "192.168.1.27", remote: "100.69.43.83"),
                            session: URLSession(configuration: config))
    }

    @Test func cancelledViewDoesNotBreakRouteSearch() async throws {
        let client = client()
        // Erste Ansicht wird mitten in der Suche verlassen (Tab-Wechsel) …
        let first = Task { try await client.get("/api/app/test", as: Status.self) }
        try await Task.sleep(for: .milliseconds(50))
        first.cancel()
        // … die zweite bekommt trotzdem eine Verbindung, ohne von vorn zu proben.
        let status = try await client.get("/api/app/test", as: Status.self)
        #expect(status.running == false)
        #expect(await client.route == .remote)
        #expect(StubProtocol.probes == 2)  // WLAN + Tailscale je einmal
    }

    @Test func withoutWifiTailscaleComesFirst() async throws {
        let client = client()
        await client.setNetwork(wifiAvailable: false)
        _ = try await client.get("/api/app/test", as: Status.self)
        #expect(await client.route == .remote)
        #expect(StubProtocol.probes == 1)  // Heim-IP gar nicht erst probiert
    }

    @Test func unreachableNamesEveryAttempt() async {
        let client = client()
        StubProtocol.reachableHosts = []
        do {
            _ = try await client.get("/api/app/test", as: Status.self)
            Issue.record("hätte scheitern müssen")
        } catch {
            let text = error.localizedDescription
            #expect(text.contains("192.168.1.27:8080"))
            #expect(text.contains("100.69.43.83:8080"))
            #expect(text.contains("Port?"))
        }
    }
}

@Suite struct BriefingDocumentTests {
    // Synthetisch, aber in der Form der echten Telegram-HTML-Briefings.
    static let sample = """
    <b>📊 BRIEFING — Donnerstag, 08.10.2026</b>

    <b>1. MARKTLAGE</b>
    Regime <b>Neutral</b> — [Fakt] die <b>US-10Y</b> steigt &amp; Öl <i>auch</i>.
    Zweite Zeile im selben Absatz.

    <b>2b) STOP-CHECK — offene Flanke</b>
    <b>17 Positionen ungesichert.</b>
    • <b>NVDA</b>: Stop <code>226 USD</code> [Einschätzung]
    • <b>AVGO</b>: hochziehen

    <b>4. EMPFEHLUNGEN</b>
    1. <b>Gold aufstocken</b>: +2 Stk
    2. <b>NVDA Stop 226</b> setzen

    <b>7. EMPFEHLUNGS-BILANZ</b>
    Hit-Rate 57%.
    """

    @Test func splitsIntoSections() {
        let doc = BriefingDocument.parse(Self.sample)
        #expect(doc.title == "📊 BRIEFING — Donnerstag, 08.10.2026")
        #expect(doc.sections.map(\.number) == ["1", "2b", "4", "7"])
        #expect(doc.sections.map(\.kind) == [.market, .stops, .recommendations, .track])
        #expect(doc.sections[0].displayTitle == "Marktlage")
        #expect(doc.sections[1].displayTitle == "Stop-Check")
        #expect(doc.sections[1].subtitle == "offene Flanke")
        #expect(doc.sections[3].displayTitle == "Empfehlungs-Bilanz")
    }

    @Test func blocksAndInlineFormatting() {
        let doc = BriefingDocument.parse(Self.sample)
        let market = doc.sections[0]
        #expect(market.blocks.count == 1)  // zwei Zeilen, ein Absatz
        let runs = market.blocks[0].runs
        #expect(runs.contains { $0.text == "Neutral" && $0.bold })
        #expect(runs.contains { $0.text == "Fakt" && $0.tag })
        #expect(runs.contains { $0.text == "auch" && $0.italic })
        #expect(InlineRun.plainText(runs).contains("steigt & Öl"))
        #expect(!InlineRun.plainText(runs).contains("<"))

        let stops = doc.sections[1]
        // Fette Satzzeile mitten im Abschnitt bleibt Text, wird kein neuer Abschnitt.
        guard case .paragraph(let p) = stops.blocks[0] else { Issue.record("Absatz erwartet"); return }
        #expect(p.first?.bold == true)
        guard case .bullet(let b) = stops.blocks[1] else { Issue.record("Aufzählung erwartet"); return }
        #expect(b.contains { $0.text == "226 USD" && $0.code })
        #expect(b.contains { $0.text == "Einschätzung" && $0.tag })

        guard case .numbered(let n, let item) = doc.sections[2].blocks[0] else { Issue.record("Nummer erwartet"); return }
        #expect(n == "1")
        #expect(item.first?.text == "Gold aufstocken")
    }

    @Test func markdownAndParenthesisHeadings() {
        let doc = BriefingDocument.parse("""
        **1) MARKTLAGE**
        Ruhig.
        ## Risiken
        - **Zinsen** steigen
        """)
        #expect(doc.title == nil)
        #expect(doc.sections.map(\.displayTitle) == ["Marktlage", "Risiken"])
        #expect(doc.sections[1].kind == .risks)
        #expect(doc.sections[1].blocks.first?.runs.first == InlineRun(text: "Zinsen", bold: true))
    }

    @Test func textWithoutHeadingsBecomesOverview() {
        let doc = BriefingDocument.parse("Nur ein Satz ohne Gliederung.")
        #expect(doc.sections.count == 1)
        #expect(doc.sections[0].title == "Überblick")
        #expect(doc.sections[0].preview == "Nur ein Satz ohne Gliederung.")
    }

    @Test func lessThanSignIsNotATag() {
        #expect(InlineRun.plain("RSI <30 und <b>fett</b>") == "RSI <30 und fett")
    }
}

@Suite struct StopAndOrderTests {
    @Test func stopKeepsBrokerCurrency() throws {
        let s = try decode(StopPosition.self, """
        {"ticker": "AVGO", "name": "Broadcom", "account": "trade_republic", "status": "ok", "currency": "USD",
         "ist_stop": 349.44, "ist_stop_broker": 312.0, "stop_currency": "EUR", "shares": 6.7, "wert_eur": 2093}
        """)
        #expect(s.brokerStop == 312)
        #expect(s.brokerCurrency == "EUR")
        #expect(s.stopInOtherCurrency)
        let old = try decode(StopPosition.self, #"{"ticker": "NVDA", "currency": "USD", "ist_stop": 226, "status": "ok"}"#)
        #expect(old.brokerStop == 226)
        #expect(old.brokerCurrency == "USD")
        #expect(!old.stopInOtherCurrency)
    }

    @Test func euroHintOnlyForDollar() {
        #expect(abs((Format.eurValue(112, currency: "USD", eurUsd: 1.12) ?? 0) - 100) < 1e-9)
        #expect(Format.eurValue(100, currency: "EUR", eurUsd: 1.12) == nil)
        #expect(Format.eurValue(100, currency: "USD", eurUsd: nil) == nil)
        #expect(Format.currencyCode("€") == "EUR")
        #expect(Format.price(10, currency: "€").contains("€"))
    }

    @Test func holdBecomesStopAction() throws {
        let raise = try decode(Recommendation.self, """
        {"ticker": "AVGO", "action": "hold", "stop_loss": 350, "status": "open", "current_stop": 333, "name": "Broadcom"}
        """)
        #expect(raise.actionLabel == "Stop nachziehen")
        #expect(raise.isStopAction)
        #expect(raise.displayName == "Broadcom")
        #expect((raise.stopRaisePct ?? 0) > 5)
        let fresh = try decode(Recommendation.self, #"{"ticker": "NVDA", "action": "hold", "stop_loss": 226, "status": "open"}"#)
        #expect(fresh.actionLabel == "Stop setzen")
        let plain = try decode(Recommendation.self, #"{"ticker": "X", "action": "hold", "status": "open"}"#)
        #expect(plain.actionLabel == "Halten")
        #expect(!plain.isActionable)
    }

    @Test func orderExpiry() throws {
        let order = try decode(Order.self, #"{"id": "o1", "ticker": "8PSG.DE", "action": "buy", "shares": 2, "limit_price": 353, "valid_until": "2026-10-30"}"#)
        #expect(order.volume == 706)
        #expect(!order.isExpired(now: VeloraDate.parse("2026-10-30T18:00:00")!))
        #expect(order.isExpired(now: VeloraDate.parse("2026-10-31T09:00:00")!))
    }
}
