import SwiftUI
import VeloraKit

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    @State private var lan = ""
    @State private var remote = ""
    @State private var password = ""
    @State private var testResult: String?
    @State private var testing = false

    @State private var server: ServerSettings?
    @State private var version: SystemVersion?
    @State private var days: Set<String> = []
    @State private var time = Date.now
    @State private var savingSchedule = false
    @State private var scheduleMessage: String?
    @State private var error: String?

    @State private var preferences: [String: NotificationPreference] = [:]
    @State private var testingPush = false
    @State private var pushTestResult: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    LabeledContent("Heim-WLAN") {
                        TextField("http://192.168.1.10:8080", text: $lan)
                            .multilineTextAlignment(.trailing)
                    }
                    LabeledContent("Tailscale") {
                        TextField("100.x.y.z:8080", text: $remote)
                            .multilineTextAlignment(.trailing)
                    }
                    LabeledContent("Passwort") {
                        SecureField("keines", text: $password)
                            .multilineTextAlignment(.trailing)
                    }
                    Button {
                        Task { await testConnection() }
                    } label: {
                        HStack {
                            Text("Verbindung prüfen")
                            Spacer()
                            if testing { ProgressView() } else if let testResult { Text(testResult).foregroundStyle(.secondary) }
                        }
                    }
                } header: {
                    Text("Server")
                } footer: {
                    Text("Velora versucht zuerst die WLAN-Adresse und nimmt unterwegs automatisch Tailscale (Tailscale-App am iPhone muss verbunden sein). Ohne Port-Angabe wird 8080 verwendet. Das Passwort ist nur nötig, wenn am Pi web.auth_token gesetzt ist.")
                }
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)

                if let server {
                    Section {
                        LabeledContent("Briefing-Tage") {
                            HStack(spacing: 4) {
                                ForEach(Format.weekdays, id: \.key) { day in
                                    let on = days.contains(day.key)
                                    Button(day.label) {
                                        if on { days.remove(day.key) } else { days.insert(day.key) }
                                    }
                                    .font(.caption.weight(.semibold))
                                    .frame(width: 28, height: 28)
                                    .background(on ? Theme.accent : Color.secondary.opacity(0.2), in: .circle)
                                    .foregroundStyle(on ? .white : .secondary)
                                    .buttonStyle(.plain)
                                }
                            }
                        }
                        DatePicker("Uhrzeit", selection: $time, displayedComponents: .hourAndMinute)
                        Button(savingSchedule ? "Wird gespeichert …" : "Zeitplan speichern") { Task { await saveSchedule() } }
                            .disabled(savingSchedule || days.isEmpty)
                    } header: {
                        Text("Briefings")
                    } footer: {
                        if let scheduleMessage {
                            Text(scheduleMessage)
                        } else {
                            Text("Neue Briefings stehen im Berater-Tab – mit Mitteilungen bekommst du sie zusätzlich aufs iPhone.")
                        }
                    }
                    Section("Konto") {
                        if let tax = server.taxRegime { LabeledContent("Steuer", value: tax) }
                        LabeledContent("KESt-Verrechnung", value: server.kestMode == "global" ? "über alle Depots" : "je Depot")
                        if let ccy = server.defaultCurrency { LabeledContent("Standardwährung", value: ccy) }
                    }
                }

                notificationsSection

                Section("Server-Software") {
                    if let version, version.available {
                        LabeledContent("Version", value: version.shortSha ?? "–")
                        if let subject = version.subject { Text(subject).font(.footnote).foregroundStyle(.secondary) }
                        if let date = version.date { LabeledContent("Stand", value: Format.date(date)) }
                    } else {
                        Text("Nicht verfügbar").foregroundStyle(.secondary)
                    }
                    if let url = currentWebURL {
                        Link(destination: url) { Label("Web-Dashboard öffnen", systemImage: "safari") }
                    }
                }

                Section {
                    LabeledContent("App", value: Bundle.main.versionString)
                }
            }
            .navigationTitle("Einstellungen")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Fertig") {
                        Task {
                            await applyServer()
                            dismiss()
                        }
                    }
                }
            }
            .task { await loadInitial() }
            // Auch beim Wegwischen übernehmen, nicht nur über „Fertig“.
            .onDisappear { Task { await applyServer() } }
            .errorAlert($error)
        }
    }

    @ViewBuilder private var notificationsSection: some View {
        Section {
            if PushEnvironment.current == nil {
                Text("Dieser Build kann keine Mitteilungen empfangen. Dafür braucht es einen bezahlten Apple-Developer-Account (siehe ios/README.md). Briefings findest du im Berater-Tab.")
                    .font(.footnote).foregroundStyle(.secondary)
            } else if model.notificationsAllowed == false {
                Button("In den iOS-Einstellungen erlauben", systemImage: "bell.slash") {
                    if let url = URL(string: UIApplication.openNotificationSettingsURLString) {
                        UIApplication.shared.open(url)
                    }
                }
            } else {
                ForEach(NotificationCategory.allCases) { category in
                    if let pref = preferences[category.rawValue] {
                        Toggle(category.title, isOn: Binding(
                            get: { pref.pushEnabled },
                            set: { on in Task { await setPush(category, on) } }
                        ))
                    }
                }
                Button {
                    Task { await sendTestPush() }
                } label: {
                    HStack {
                        Text("Test-Mitteilung senden")
                        Spacer()
                        if testingPush { ProgressView() } else if let pushTestResult { Text(pushTestResult).foregroundStyle(.secondary) }
                    }
                }
            }
        } header: {
            Text("Mitteilungen")
        } footer: {
            if let pushError = model.pushError {
                Text("iPhone nicht angemeldet: \(pushError)")
            } else {
                Text("Die Schalter gelten auch für die Web-App. Systemfehler kommen zusätzlich per Telegram, falls keine Mitteilung zugestellt werden konnte.")
            }
        }
    }

    private func setPush(_ category: NotificationCategory, _ on: Bool) async {
        let previous = preferences[category.rawValue]
        preferences[category.rawValue]?.pushEnabled = on
        do {
            try await model.client.send("/api/push/preferences", body: [category.rawValue: .object(["push_enabled": .bool(on)])])
        } catch {
            preferences[category.rawValue] = previous
            self.error = error.localizedDescription
        }
    }

    private func sendTestPush() async {
        testingPush = true
        defer { testingPush = false }
        await model.registerPushToken()
        nonisolated struct TestResult: Decodable { var sent: Int }
        do {
            let result: TestResult = try await model.client.post("/api/push/test", body: [String: String]())
            pushTestResult = result.sent > 0 ? "✓ an \(result.sent) Gerät\(result.sent == 1 ? "" : "e")" : "✕ nicht zugestellt"
        } catch {
            pushTestResult = "✕ fehlgeschlagen"
            self.error = error.localizedDescription
        }
    }

    private var currentWebURL: URL? {
        let endpoints = model.endpoints
        return model.route == .remote ? ServerEndpoints.url(from: endpoints.remote) : ServerEndpoints.url(from: endpoints.lan)
    }

    private var changed: Bool {
        lan != model.endpoints.lan || remote != model.endpoints.remote || password != model.password
    }

    private func applyServer() async {
        guard changed else { return }
        await model.updateServer(ServerEndpoints(lan: lan, remote: remote), password: password)
    }

    private func loadInitial() async {
        lan = model.endpoints.lan
        remote = model.endpoints.remote
        password = model.password
        await loadServerInfo()
    }

    private func loadServerInfo() async {
        server = try? await model.client.get("/api/settings")
        version = try? await model.client.get("/api/system/version")
        preferences = (try? await model.client.get("/api/push/preferences")) ?? preferences
        if let server {
            days = Set(server.briefingDays)
            let parts = (server.briefingTime ?? "07:00").split(separator: ":").compactMap { Int($0) }
            time = Calendar.current.date(bySettingHour: parts.first ?? 7, minute: parts.dropFirst().first ?? 0, second: 0, of: .now) ?? .now
        }
    }

    private func testConnection() async {
        testing = true
        defer { testing = false }
        await applyServer()
        await model.client.invalidateRoute()
        do {
            nonisolated struct Status: Decodable { var running: Bool }
            let _: Status = try await model.client.get("/api/refresh/status")
            let route = await model.client.route
            testResult = "✓ verbunden über \(route?.rawValue ?? "?")"
            await loadServerInfo()
        } catch {
            testResult = "✕ nicht erreichbar"
            self.error = error.localizedDescription
        }
    }

    private func saveSchedule() async {
        savingSchedule = true
        defer { savingSchedule = false }
        let c = Calendar.current.dateComponents([.hour, .minute], from: time)
        let hhmm = String(format: "%02d:%02d", c.hour ?? 7, c.minute ?? 0)
        let ordered = Format.weekdays.map(\.key).filter(days.contains)
        do {
            let result = try await model.client.send("/api/settings", body: [
                "schedule": .object(["briefing_days": .array(ordered.map(JSONValue.string)), "briefing_time": .string(hhmm)]),
            ])
            // Der Server meldet, ob der Zeitplan auch in der Crontab angekommen ist.
            scheduleMessage = result.message
        } catch {
            self.error = error.localizedDescription
        }
    }
}

private extension Bundle {
    var versionString: String {
        let v = infoDictionary?["CFBundleShortVersionString"] as? String ?? "?"
        let b = infoDictionary?["CFBundleVersion"] as? String ?? "?"
        return "\(v) (\(b))"
    }
}
