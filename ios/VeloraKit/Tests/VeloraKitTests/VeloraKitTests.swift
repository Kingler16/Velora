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
