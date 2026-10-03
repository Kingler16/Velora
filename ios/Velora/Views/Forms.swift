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

    @Environment(AppModel.self) private var model
    @State private var form = (ticker: "", action: "buy", account: "", shares: "", limit: "", currency: "EUR", note: "")

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
                TextField("Notiz (optional)", text: $form.note)
            } footer: {
                Text("Die Order landet in der Order-Liste und ändert das Depot noch nicht. Erst „Ausgeführt“ bucht die Position ein. Beim Broker musst du sie selbst aufgeben.")
            }
        }
        .onAppear {
            form.ticker = ticker
            form.action = action == "sell" ? "sell" : "buy"
            form.currency = currency
            form.account = accounts.first ?? ""
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
    var stop: Double?
    var accounts: [String]

    @Environment(AppModel.self) private var model
    @State private var form = (shares: "", buyIn: "", stop: "", account: "", name: "")

    var body: some View {
        FormSheet(title: position.ticker, canSave: (parseNumber(form.shares) ?? 0) > 0, save: save) {
            Section("Bestand") {
                TextField("Name", text: $form.name)
                NumberField(title: "Stück", text: $form.shares)
                NumberField(title: "Kaufkurs (\(position.currency))", text: $form.buyIn)
                AccountPicker(accounts: accounts, selection: $form.account)
            }
            Section {
                NumberField(title: "Stop-Loss (\(position.currency))", text: $form.stop, prompt: "kein Stop")
            } header: {
                Text("Stop-Loss")
            } footer: {
                Text("Der beim Broker tatsächlich gesetzte Stop, in der Notierungswährung. Leer lassen = kein Stop.")
            }
        }
        .onAppear {
            form.shares = Format.plain(position.shares)
            form.buyIn = position.buyIn.map { Format.plain($0) } ?? ""
            form.stop = stop.map { Format.plain($0) } ?? ""
            form.account = position.account
            form.name = position.name
        }
    }

    private func save() async throws {
        var body: [String: JSONValue] = [
            "account": .string(position.account), "ticker": .string(position.ticker),
            "shares": JSONValue(parseNumber(form.shares)),
            "stop_loss": JSONValue(parseNumber(form.stop)),
        ]
        if let buyIn = parseNumber(form.buyIn), buyIn != position.buyIn { body["buy_in"] = .number(buyIn) }
        if form.name != position.name, !form.name.isEmpty { body["name"] = .string(form.name) }
        if form.account != position.account { body["new_account"] = .string(form.account) }
        try await model.send("/api/portfolio/position/edit", body)
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
