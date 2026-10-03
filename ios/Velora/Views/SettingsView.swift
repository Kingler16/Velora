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
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    LabeledContent("Heim-WLAN") {
                        TextField("http://192.168.1.27:8080", text: $lan)
                            .multilineTextAlignment(.trailing)
                    }
                    LabeledContent("Tailscale") {
                        TextField("http://rockpi:8080", text: $remote)
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
                    Text("Velora versucht zuerst die WLAN-Adresse und nimmt unterwegs automatisch Tailscale (Tailscale-App am iPhone muss verbunden sein). Das Passwort ist nur nötig, wenn am Pi web.auth_token gesetzt ist.")
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
                        Text("Die Briefings selbst bekommst du weiterhin per Telegram bzw. als Mitteilung der Web-App.")
                    }
                    Section("Konto") {
                        if let tax = server.taxRegime { LabeledContent("Steuer", value: tax) }
                        LabeledContent("KESt-Verrechnung", value: server.kestMode == "global" ? "über alle Depots" : "je Depot")
                        if let ccy = server.defaultCurrency { LabeledContent("Standardwährung", value: ccy) }
                    }
                }

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
            .errorAlert($error)
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
            testResult = "✕ " + ((error as? VeloraError) == nil ? "Fehler" : "nicht erreichbar")
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
            try await model.client.send("/api/settings", body: [
                "schedule": .object(["briefing_days": .array(ordered.map(JSONValue.string)), "briefing_time": .string(hhmm)]),
            ])
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
