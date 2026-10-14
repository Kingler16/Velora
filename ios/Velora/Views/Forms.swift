import SwiftUI
import VeloraKit

/// Gemeinsamer Rahmen: Abbrechen/Sichern, Fortschritt, Fehlermeldung.
private struct FormSheet<Content: View>: View {
    var title: String
    var saveTitle = "Sichern"
    var canSave: Bool
    var save: () async throws -> Void
    @ViewBuilder var content: Content

    @Environment(\.dismiss) private var dismiss
    @State private var saving = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form { content }
                .navigationTitle(title)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("Abbrechen") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) {
                        if saving {
                            ProgressView()
                        } else {
                            Button(saveTitle) {
                                Task {
                                    saving = true
                                    defer { saving = false }
                                    do { try await save(); dismiss() } catch { self.error = error.localizedDescription }
                                }
                            }
                            .disabled(!canSave)
                        }
                    }
                }
                .errorAlert($error)
        }
        .presentationDetents([.large])
    }
}

private struct AccountPicker: View {
    var accounts: [String]
    @Binding var selection: String

    var body: some View {
        Picker("Depot", selection: $selection) {
            ForEach(accounts, id: \.self) { Text(Format.accountName($0)).tag($0) }
        }
    }
}

private struct CurrencyPicker: View {
    @Binding var selection: String

    var body: some View {
        Picker("Währung", selection: $selection) {
            ForEach(["EUR", "USD", "GBP", "CHF", "CAD"], id: \.self) { Text($0).tag($0) }
        }
    }
}

private struct NumberField: View {
    var title: String
    @Binding var text: String
    var prompt = ""

    var body: some View {
        LabeledContent(title) {
            TextField(title, text: $text, prompt: Text(prompt))
                .keyboardType(.decimalPad)
                .multilineTextAlignment(.trailing)
                .monospacedDigit()
        }
    }
}

// MARK: - Kauf/Verkauf

struct TradeSheet: View {
    var position: Position?
    var accounts: [String]
    var presetTicker: String?
    var presetCurrency: String?

    @Environment(AppModel.self) private var model
    @State private var action = "buy"
    @State private var ticker = ""
    @State private var account = ""
    @State private var shares = ""
    @State private var price = ""
    @State private var currency = "EUR"

    var body: some View {
        FormSheet(title: "Trade erfassen", canSave: valid, save: save) {
            Section {
                Picker("Art", selection: $action) {
                    Text("Kauf").tag("buy")
                    Text("Verkauf").tag("sell")
                }
                .pickerStyle(.segmented)
                TextField("Ticker (z. B. AAPL, EUNL.DE)", text: $ticker)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
                AccountPicker(accounts: accounts, selection: $account)
            }
            Section {
                NumberField(title: "Stück", text: $shares, prompt: "0")
                NumberField(title: "Preis je Stück", text: $price, prompt: "0,00")
                CurrencyPicker(selection: $currency)
                if let s = parseNumber(shares), let p = parseNumber(price) {
                    LabeledContent("Volumen", value: Format.price(s * p, currency: currency))
                }
            } footer: {
                Text("Wird sofort ins Depot gebucht, inkl. Cash. Passende offene Empfehlungen werden automatisch geschlossen.")
            }
        }
        .onAppear {
            ticker = position?.ticker ?? presetTicker ?? ""
            account = position?.account ?? accounts.first ?? ""
            currency = position?.currency ?? presetCurrency ?? "EUR"
        }
    }

    private var valid: Bool {
        !ticker.isEmpty && !account.isEmpty && (parseNumber(shares) ?? 0) > 0 && (parseNumber(price) ?? 0) > 0
    }

    private func save() async throws {
        try await model.send("/api/trade", [
            "action": .string(action), "ticker": .string(ticker.uppercased()), "account": .string(account),
            "shares": JSONValue(parseNumber(shares)), "price": JSONValue(parseNumber(price)),
            "trade_currency": .string(currency),
        ])
    }
}

// MARK: - Orders

struct OrderSheet: View {
    var ticker: String
    var action: String
    var currency: String
    var accounts: [String]
    var recTicker: String?
    var presetAccount: String?
    var presetShares: Double?
    var presetLimit: Double?

    @Environment(AppModel.self) private var model
    @State private var form = (ticker: "", action: "buy", account: "", shares: "", limit: "", currency: "EUR", note: "")
    @State private var hasExpiry = false
    @State private var validUntil = Calendar.current.date(byAdding: .day, value: 30, to: .now) ?? .now

    var body: some View {
        FormSheet(title: "Limit-Order", saveTitle: "Platzieren", canSave: valid, save: save) {
            Section {
                Picker("Art", selection: $form.action) {
                    Text("Kauf").tag("buy")
                    Text("Verkauf").tag("sell")
                }
                .pickerStyle(.segmented)
                TextField("Ticker", text: $form.ticker)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
                AccountPicker(accounts: accounts, selection: $form.account)
            }
            Section {
                NumberField(title: "Stück", text: $form.shares, prompt: "0")
                NumberField(title: "Limit", text: $form.limit, prompt: "0,00")
                CurrencyPicker(selection: $form.currency)
                if let s = parseNumber(form.shares), let l = parseNumber(form.limit) {
                    LabeledContent("Volumen", value: Format.price(s * l, currency: form.currency))
                }
                Toggle("Gültig bis", isOn: $hasExpiry.animation())
                if hasExpiry {
                    DatePicker("Datum", selection: $validUntil, in: Date.now..., displayedComponents: .date)
                }
                TextField("Notiz (optional)", text: $form.note)
            } footer: {
                Text("Die Order landet in der Order-Liste und ändert das Depot noch nicht. Erst „Ausgeführt“ bucht die Position ein. Beim Broker musst du sie selbst aufgeben.")
            }
        }
        .onAppear {
            form.ticker = ticker
            form.action = action == "sell" ? "sell" : "buy"
            form.currency = Format.currencyCode(currency)
            form.account = presetAccount.flatMap { accounts.contains($0) ? $0 : nil } ?? accounts.first ?? ""
            if let presetShares { form.shares = Format.plain(presetShares) }
            if let presetLimit { form.limit = Format.plain(presetLimit, digits: 2) }
        }
    }

    private var valid: Bool {
        !form.ticker.isEmpty && (parseNumber(form.shares) ?? 0) > 0 && (parseNumber(form.limit) ?? 0) > 0
    }

    private func save() async throws {
        try await model.send("/api/orders/place", [
            "ticker": .string(form.ticker.uppercased()), "action": .string(form.action),
            "shares": JSONValue(parseNumber(form.shares)), "limit_price": JSONValue(parseNumber(form.limit)),
            "account": .string(form.account), "currency": .string(form.currency),
            "rec_ticker": JSONValue(recTicker), "note": JSONValue(form.note.isEmpty ? nil : form.note),
            "valid_until": JSONValue(hasExpiry ? validUntil.formatted(.iso8601.year().month().day()) : nil),
        ])
    }
}

struct FillOrderSheet: View {
    var order: Order

    @Environment(AppModel.self) private var model
    @State private var price = ""
    @State private var date = Date.now

    var body: some View {
        FormSheet(title: "Order ausgeführt", saveTitle: "Buchen", canSave: (parseNumber(price) ?? 0) > 0, save: save) {
            Section {
                OrderRow(order: order)
            }
            Section {
                NumberField(title: "Ausführungskurs", text: $price)
                DatePicker("Datum", selection: $date, in: ...Date.now, displayedComponents: .date)
            } footer: {
                Text("Bucht \(Format.shares(order.shares)) Stück \(order.ticker) ins Depot \(Format.accountName(order.account)).")
            }
        }
        .onAppear { price = order.limitPrice.map { Format.plain($0) } ?? "" }
    }

    private func save() async throws {
        let day = date.formatted(.iso8601.year().month().day())
        try await model.send("/api/orders/fill", [
            "id": .string(order.id), "fill_price": JSONValue(parseNumber(price)), "fill_date": .string(day),
        ])
    }
}

/// Stop beim Broker ausgelöst → Verkauf nachbuchen (inkl. Cash), wie „Ausgeführt“ bei Limit-Orders.
struct FillStopSheet: View {
    var stop: StopPosition

    @Environment(AppModel.self) private var model
    @State private var price = ""
    @State private var currency = "EUR"
    @State private var shares = ""
    @State private var date = Date.now

    var body: some View {
        FormSheet(title: "Stop ausgelöst", saveTitle: "Buchen", canSave: valid, save: save) {
            Section {
                LabeledContent(stop.displayName, value: Format.accountName(stop.account))
                if let broker = stop.brokerStop {
                    LabeledContent("Stop beim Broker", value: Format.price(broker, currency: stop.brokerCurrency))
                }
            }
            Section {
                NumberField(title: "Ausführungskurs", text: $price)
                CurrencyPicker(selection: $currency)
                NumberField(title: "Stück", text: $shares)
                DatePicker("Datum", selection: $date, in: ...Date.now, displayedComponents: .date)
                if let s = parseNumber(shares), let p = parseNumber(price) {
                    LabeledContent("Erlös", value: Format.price(s * p, currency: currency))
                }
            } footer: {
                Text("Trag den Kurs so ein, wie er in der Abrechnung steht (Slippage möglich). Bucht den Verkauf inkl. Cash ins Depot \(Format.accountName(stop.account)). Bei vollem Verkauf verschwindet die Position samt Stop.")
            }
        }
        .onAppear {
            price = stop.brokerStop.map { Format.plain($0, digits: 2) } ?? ""
            currency = stop.brokerCurrency
            shares = stop.shares.map { Format.plain($0) } ?? ""
        }
    }

    private var valid: Bool {
        (parseNumber(price) ?? 0) > 0 && (parseNumber(shares) ?? 0) > 0
    }

    private func save() async throws {
        try await model.send("/api/trade", [
            "action": .string("sell"), "ticker": .string(stop.ticker), "account": .string(stop.account),
            "shares": JSONValue(parseNumber(shares)), "price": JSONValue(parseNumber(price)),
            "trade_currency": .string(currency),
            "trade_date": .string(date.formatted(.iso8601.year().month().day())),
        ])
    }
}

// MARK: - Bestandskorrekturen

struct AddPositionSheet: View {
    var accounts: [String]

    @Environment(AppModel.self) private var model
    @State private var form = (ticker: "", name: "", isin: "", account: "", shares: "", buyIn: "", currency: "EUR")

    var body: some View {
        FormSheet(title: "Bestand nachtragen", canSave: valid, save: save) {
            Section {
                TextField("Ticker", text: $form.ticker)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
                TextField("Name", text: $form.name)
                TextField("ISIN (optional)", text: $form.isin)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
                AccountPicker(accounts: accounts, selection: $form.account)
            }
            Section {
                NumberField(title: "Stück", text: $form.shares)
                NumberField(title: "Kaufkurs", text: $form.buyIn)
                CurrencyPicker(selection: $form.currency)
            } footer: {
                Text("Für Positionen, die du schon hältst. Kein Cash-Effekt – für neue Käufe „Kauf/Verkauf erfassen“ verwenden.")
            }
        }
        .onAppear { form.account = accounts.first ?? "" }
    }

    private var valid: Bool {
        !form.ticker.isEmpty && !form.account.isEmpty && (parseNumber(form.shares) ?? 0) > 0 && (parseNumber(form.buyIn) ?? 0) > 0
    }

    private func save() async throws {
        try await model.send("/api/portfolio/position/add", [
            "account": .string(form.account), "ticker": .string(form.ticker.uppercased()),
            "shares": JSONValue(parseNumber(form.shares)), "buy_in": JSONValue(parseNumber(form.buyIn)),
            "currency": .string(form.currency), "name": .string(form.name), "isin": .string(form.isin.uppercased()),
        ])
    }
}

struct EditPositionSheet: View {
    var position: Position
    var stop: StopPosition?
    var accounts: [String]

    @Environment(AppModel.self) private var model
    @State private var form = (shares: "", buyIn: "", stop: "", stopCurrency: "EUR", account: "", name: "")

    var body: some View {
        FormSheet(title: position.ticker, canSave: (parseNumber(form.shares) ?? 0) > 0, save: save) {
            Section("Bestand") {
                TextField("Name", text: $form.name)
                NumberField(title: "Stück", text: $form.shares)
                NumberField(title: "Kaufkurs (\(Format.currencyCode(position.currency)))", text: $form.buyIn)
                AccountPicker(accounts: accounts, selection: $form.account)
            }
            Section {
                NumberField(title: "Stop-Loss", text: $form.stop, prompt: "kein Stop")
                StopCurrencyPicker(selection: $form.stopCurrency)
            } header: {
                Text("Stop-Loss")
            } footer: {
                Text("Der beim Broker tatsächlich gesetzte Stop, in der Währung, in der er dort steht. Leer lassen = kein Stop.")
            }
        }
        .onAppear {
            form.shares = Format.plain(position.shares)
            form.buyIn = position.buyIn.map { Format.plain($0) } ?? ""
            form.stop = stop?.brokerStop.map { Format.plain($0, digits: 2) } ?? ""
            form.stopCurrency = stop?.stopCurrency
                ?? StopDefaults.currency(account: position.account, quote: stop?.currency ?? position.currency)
            form.account = position.account
            form.name = position.name
        }
    }

    private func save() async throws {
        var body: [String: JSONValue] = [
            "account": .string(position.account), "ticker": .string(position.ticker),
            "shares": JSONValue(parseNumber(form.shares)),
            "stop_loss": JSONValue(parseNumber(form.stop)),
            "stop_currency": .string(form.stopCurrency),
        ]
        if let buyIn = parseNumber(form.buyIn), buyIn != position.buyIn { body["buy_in"] = .number(buyIn) }
        if form.name != position.name, !form.name.isEmpty { body["name"] = .string(form.name) }
        if form.account != position.account { body["new_account"] = .string(form.account) }
        try await model.send("/api/portfolio/position/edit", body)
    }
}

// MARK: - Stops

/// Wo ein Stop gespeichert wird und was vorgeschlagen ist.
struct StopTarget: Identifiable, Hashable {
    var id: String { "\(account)|\(ticker)" }
    var account: String
    var ticker: String
    var name: String
    /// Notierungswährung des Titels.
    var quoteCurrency: String
    var currentPrice: Double?
    var brokerStop: Double?
    var brokerCurrency: String?
    /// Vorschlag in Notierungswährung (Soll-Stop oder neuer Stop aus der Empfehlung).
    var suggestion: Double?
    var suggestionLabel = "Vorschlag"
    /// Empfehlung, die mit dem Eintragen erledigt ist.
    var recommendationTicker: String?

    init(stop: StopPosition) {
        account = stop.account
        ticker = stop.ticker
        name = stop.displayName
        quoteCurrency = stop.currency
        currentPrice = stop.currentPrice
        brokerStop = stop.brokerStop
        brokerCurrency = stop.stopCurrency
        suggestion = stop.targetStop
        suggestionLabel = "Soll-Stop (2×ATR)"
    }

    init?(recommendation rec: Recommendation) {
        guard let account = rec.account else { return nil }
        self.account = account
        ticker = rec.positionTicker ?? rec.ticker
        name = rec.displayName
        quoteCurrency = rec.currency
        currentPrice = rec.currentPrice
        brokerStop = rec.currentStopBroker
        brokerCurrency = rec.currentStopCurrency
        suggestion = rec.stopLoss
        suggestionLabel = "Neuer Stop laut Velora"
        recommendationTicker = rec.ticker
    }
}

enum StopDefaults {
    /// Trade Republic führt Stops auf Auslandsaktien in Euro, die übrigen Broker in der Notierungswährung.
    static func currency(account: String, quote: String) -> String {
        let q = Format.currencyCode(quote)
        if account.lowercased().contains("trade_republic") { return "EUR" }
        return ["EUR", "USD"].contains(q) ? q : "EUR"
    }
}

private struct StopCurrencyPicker: View {
    @Binding var selection: String

    var body: some View {
        Picker("Währung beim Broker", selection: $selection) {
            Text("Euro (€)").tag("EUR")
            Text("Dollar ($)").tag("USD")
        }
    }
}

/// Stop eintragen oder ändern – so, wie er beim Broker steht.
struct EditStopSheet: View {
    var target: StopTarget
    var onSaved: (() -> Void)?

    @Environment(AppModel.self) private var model
    @State private var value = ""
    @State private var currency = "EUR"
    @State private var eurUsd: Double?

    var body: some View {
        FormSheet(title: target.brokerStop == nil ? "Stop eintragen" : "Stop ändern",
                  canSave: parseNumber(value).map { $0 > 0 } ?? (target.brokerStop != nil), save: save) {
            Section {
                LabeledContent("Titel", value: target.name)
                LabeledContent("Depot", value: Format.accountName(target.account))
                if let price = target.currentPrice {
                    LabeledContent("Kurs") {
                        PriceStack(value: price, currency: target.quoteCurrency, eurUsd: eurUsd, font: .body)
                    }
                }
                if let current = target.brokerStop {
                    LabeledContent("Aktueller Stop",
                                   value: Format.price(current, currency: target.brokerCurrency ?? target.quoteCurrency))
                }
            }
            Section {
                NumberField(title: "Stop-Kurs", text: $value, prompt: "kein Stop")
                StopCurrencyPicker(selection: $currency)
                if let suggestion = target.suggestion {
                    Button {
                        value = Format.plain(converted(suggestion), digits: 2)
                    } label: {
                        LabeledContent(target.suggestionLabel) {
                            VStack(alignment: .trailing, spacing: 1) {
                                Text(Format.price(converted(suggestion), currency: currency))
                                if currency != target.quoteCurrency {
                                    Text(Format.price(suggestion, currency: target.quoteCurrency))
                                        .font(.caption2).foregroundStyle(.secondary)
                                }
                            }
                            .monospacedDigit()
                        }
                    }
                    .tint(.primary)
                }
            } footer: {
                Text("Trag den Wert genau so ein, wie er beim Broker steht – bei Trade Republic meist in Euro, bei der Erste Bank in Dollar. Leer lassen entfernt den Stop.")
            }
        }
        .onAppear {
            currency = target.brokerCurrency ?? StopDefaults.currency(account: target.account, quote: target.quoteCurrency)
            if let current = target.brokerStop, target.recommendationTicker == nil {
                value = Format.plain(current, digits: 2)
            } else if let suggestion = target.suggestion {
                value = Format.plain(converted(suggestion), digits: 2)
            }
        }
        .task { eurUsd = model.eurUsd }
        .onChange(of: currency) { old, new in
            // Unveränderten Vorschlag mitumrechnen, damit nicht Euro als Dollar gespeichert wird.
            guard let suggestion = target.suggestion,
                  value == Format.plain(convert(suggestion, to: old), digits: 2) else { return }
            value = Format.plain(convert(suggestion, to: new), digits: 2)
        }
    }

    private func converted(_ quoteValue: Double) -> Double { convert(quoteValue, to: currency) }

    private func convert(_ quoteValue: Double, to ccy: String) -> Double {
        guard let eurUsd, eurUsd > 0, ccy != target.quoteCurrency else { return quoteValue }
        if target.quoteCurrency == "USD", ccy == "EUR" { return (quoteValue / eurUsd * 100).rounded() / 100 }
        if target.quoteCurrency == "EUR", ccy == "USD" { return (quoteValue * eurUsd * 100).rounded() / 100 }
        return quoteValue
    }

    private func save() async throws {
        try await model.send("/api/portfolio/position/edit", [
            "account": .string(target.account), "ticker": .string(target.ticker),
            "stop_loss": JSONValue(parseNumber(value)), "stop_currency": .string(currency),
        ])
        if let rec = target.recommendationTicker, parseNumber(value) != nil {
            try await model.send("/api/recommendations/close", ["ticker": .string(rec), "status": .string("executed")])
        }
        onSaved?()
    }
}

// MARK: - Konten

struct BankAccountSheet: View {
    var account: BankAccount?

    @Environment(AppModel.self) private var model
    @State private var form = (key: "", bank: "", value: "", interest: "", note: "", depotCash: false)

    var body: some View {
        FormSheet(title: account == nil ? "Neues Konto" : "Konto", canSave: valid, save: save) {
            Section {
                if account == nil {
                    TextField("Kürzel (z. B. bawag_tagesgeld)", text: $form.key)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
                TextField("Bank", text: $form.bank)
                TextField("Bezeichnung", text: $form.note)
            }
            Section {
                NumberField(title: "Kontostand (€)", text: $form.value)
                NumberField(title: "Zinssatz (%)", text: $form.interest, prompt: "0")
                Toggle("Verrechnungskonto im Depot", isOn: $form.depotCash)
            }
        }
        .onAppear {
            guard let account else { return }
            form = (account.name, account.bank, Format.plain(account.value, digits: 2), Format.plain(account.interest, digits: 2),
                    account.note, account.isDepotCash)
        }
    }

    private var valid: Bool { (account != nil || !form.key.isEmpty) && parseNumber(form.value) != nil }

    private func save() async throws {
        let body: [String: JSONValue] = [
            "key": .string(account?.name ?? form.key), "bank": .string(form.bank),
            "value": JSONValue(parseNumber(form.value)), "interest": .number(parseNumber(form.interest) ?? 0),
            "note": .string(form.note), "is_depot_cash": .bool(form.depotCash),
        ]
        try await model.send(account == nil ? "/api/portfolio/bank/add" : "/api/portfolio/bank/edit", body)
    }
}
