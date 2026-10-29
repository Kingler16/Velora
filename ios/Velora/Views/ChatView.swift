import SwiftUI
import VeloraKit

struct ChatListView: View {
    @Environment(AppModel.self) private var model
    @State private var path: [ChatThread] = []
    @State private var error: String?

    var body: some View {
        NavigationStack(path: $path) {
            RemoteView(path: "/api/chat/threads") { (data: ThreadList) in
                List {
                    if data.threads.isEmpty {
                        ContentUnavailableView("Noch keine Chats", systemImage: "bubble.left.and.bubble.right",
                                               description: Text("Frag Velora zu deinem Depot, einzelnen Titeln oder der Marktlage."))
                    }
                    ForEach(data.threads.sorted { ($0.isPinned ? 0 : 1, $1.updatedAt ?? "") < ($1.isPinned ? 0 : 1, $0.updatedAt ?? "") }) { thread in
                        NavigationLink(value: thread) {
                            VStack(alignment: .leading, spacing: 3) {
                                HStack {
                                    if thread.isPinned { Image(systemName: "pin.fill").font(.caption).foregroundStyle(Theme.amber) }
                                    Text(thread.title).font(.subheadline.weight(.medium)).lineLimit(1)
                                }
                                Text("\(thread.messageCount) Nachrichten · \(Format.relative(thread.updatedAt))")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        .swipeActions {
                            Button("Löschen", systemImage: "trash", role: .destructive) {
                                act { try await model.send("/api/chat/threads/\(thread.id)", method: "DELETE") }
                            }
                        }
                        .swipeActions(edge: .leading) {
                            Button(thread.isPinned ? "Lösen" : "Anheften", systemImage: thread.isPinned ? "pin.slash" : "pin") {
                                act { try await model.send("/api/chat/threads/\(thread.id)", ["is_pinned": .bool(!thread.isPinned)], method: "PATCH") }
                            }
                            .tint(Theme.amber)
                        }
                    }
                }
            }
            .navigationTitle("Chat")
            .navigationDestination(for: ChatThread.self) { ChatThreadView(thread: $0) }
            .task(id: model.pendingChatThreadID) { await openPendingThread() }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Neuer Chat", systemImage: "square.and.pencil") {
                        act {
                            let thread: ChatThread = try await model.client.post("/api/chat/threads", body: ["title": "Neuer Chat"])
                            path.append(thread)
                        }
                    }
                }
            }
            .errorAlert($error)
        }
    }

    private func act(_ work: @escaping () async throws -> Void) {
        Task {
            do { try await work() } catch { self.error = error.localizedDescription }
        }
    }

    /// Tipp auf eine Chat-Mitteilung: genau diesen Verlauf zeigen.
    private func openPendingThread() async {
        guard let id = model.pendingChatThreadID else { return }
        model.pendingChatThreadID = nil
        if path.last?.id == id { return }
        do {
            let detail: ThreadDetail = try await model.client.get("/api/chat/threads/\(id)")
            path = [detail.thread]
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// Ein Chat-Verlauf mit Live-Antwort.
struct ChatThreadView: View {
    var thread: ChatThread

    @Environment(AppModel.self) private var model
    @State private var messages: [ChatMessage] = []
    @State private var confirmations: [PendingConfirmation] = []
    @State private var input = ""
    @State private var streaming = false
    @State private var loaded = false
    @State private var error: String?
    @State private var streamTask: Task<Void, Never>?
    /// Antwort läuft am Server weiter, ohne dass diese Ansicht mitliest (App war im Hintergrund).
    @State private var runningInBackground = false
    @Environment(\.scenePhase) private var scenePhase
    @FocusState private var inputFocused: Bool

    private static let suggestions = [
        "Wie steht mein Depot?",
        "Was sagt das letzte Briefing?",
        "Wo bin ich vom Mandat abgewichen?",
        "Welche Stops sollte ich nachziehen?",
    ]

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if loaded && messages.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Vorschläge").font(.caption).foregroundStyle(.secondary)
                            ForEach(Self.suggestions, id: \.self) { s in
                                Button(s) { input = s; send() }
                                    .buttonStyle(.bordered)
                            }
                        }
                        .padding(.top, 20)
                    }
                    ForEach(messages) { message in
                        MessageView(message: message)
                            .id(message.id)
                    }
                    ForEach(confirmations) { c in
                        ConfirmationCard(confirmation: c) { approved in confirm(c, approved: approved) }
                    }
                    if streaming && (messages.last?.role != .assistant || messages.last?.content.isEmpty == true) {
                        HStack(spacing: 8) {
                            ProgressView()
                            Text("Velora denkt nach …").font(.subheadline).foregroundStyle(.secondary)
                        }
                    } else if runningInBackground && !streaming {
                        HStack(alignment: .top, spacing: 8) {
                            ProgressView()
                            Text("Velora schreibt noch an der Antwort. Du bekommst eine Mitteilung, sobald sie da ist.")
                                .font(.subheadline).foregroundStyle(.secondary)
                        }
                    }
                    Color.clear.frame(height: 1).id("bottom")
                }
                .padding()
            }
            .scrollDismissesKeyboard(.interactively)
            .defaultScrollAnchor(.bottom)
            .onChange(of: messages.last?.content) { proxy.scrollTo("bottom", anchor: .bottom) }
            .onChange(of: confirmations.count) { withAnimation { proxy.scrollTo("bottom", anchor: .bottom) } }
        }
        .safeAreaInset(edge: .bottom) { inputBar }
        .navigationTitle(thread.title)
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        // Solange die Antwort am Server weiterläuft, regelmäßig nachsehen.
        .task(id: runningInBackground) {
            while runningInBackground, !Task.isCancelled {
                try? await Task.sleep(for: .seconds(3))
                await load(quiet: true)
            }
        }
        .onAppear { openChatThread.withLock { $0 = thread.id } }
        // Weggehen bricht die Antwort nicht ab: der Server schreibt fertig und schickt eine Mitteilung.
        .onDisappear {
            streamTask?.cancel()
            openChatThread.withLock { if $0 == thread.id { $0 = nil } }
        }
        .onChange(of: scenePhase) { _, phase in
            // Im Hintergrund die Verbindung lösen, damit der Server weiß, dass niemand mitliest.
            if phase == .background {
                streamTask?.cancel()
                openChatThread.withLock { if $0 == thread.id { $0 = nil } }
            } else if phase == .active {
                openChatThread.withLock { $0 = thread.id }
                Task { await load(quiet: true) }
            }
        }
        .errorAlert($error)
    }

    private var inputBar: some View {
        HStack(alignment: .bottom, spacing: 8) {
            TextField("Nachricht an Velora", text: $input, axis: .vertical)
                .lineLimit(1...6)
                .focused($inputFocused)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .glassEffect(.regular, in: .rect(cornerRadius: 22))
            if streaming {
                Button(action: stop) {
                    Image(systemName: "stop.fill").font(.body.weight(.semibold)).frame(width: 40, height: 40)
                }
                .buttonStyle(.glass)
                .accessibilityLabel("Antwort abbrechen")
            } else {
                Button(action: send) {
                    Image(systemName: "arrow.up").font(.body.weight(.bold)).frame(width: 40, height: 40)
                }
                .buttonStyle(.glassProminent)
                .disabled(input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .accessibilityLabel("Senden")
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
    }

    /// `quiet`: beim Nachsehen im Hintergrund keine Fehlermeldung (Funkloch), nur beim Öffnen.
    private func load(quiet: Bool = false) async {
        do {
            let detail: ThreadDetail = try await model.client.get("/api/chat/threads/\(thread.id)")
            // Während live gestreamt wird, nicht die halbe Antwort mit dem Serverstand überschreiben.
            guard !streaming else { return }
            messages = detail.messages.filter { $0.role != .other }
            runningInBackground = detail.running
            nonisolated struct Pending: Decodable { var pending: [PendingConfirmation] }
            let pending: Pending? = try? await model.client.get("/api/chat/pending?thread_id=\(thread.id)")
            confirmations = pending?.pending ?? []
        } catch {
            if !quiet { self.error = error.localizedDescription }
        }
        loaded = true
    }

    private func send() {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !streaming else { return }
        input = ""
        messages.append(ChatMessage(role: .user, content: text))
        streaming = true
        streamTask = Task {
            defer { streaming = false }
            var answerIndex: Int?
            do {
                for try await event in await model.client.chatStream(threadID: thread.id, message: text) {
                    switch event {
                    case .token(let token):
                        if let i = answerIndex {
                            messages[i].content += token
                        } else {
                            messages.append(ChatMessage(role: .assistant, content: token))
                            answerIndex = messages.count - 1
                        }
                    case .toolUse(let tool):
                        messages.append(ChatMessage(role: .toolUse, content: "", tool: tool))
                        answerIndex = nil  // Text nach dem Werkzeug kommt in eine neue Blase
                    case .confirmationRequired(let c):
                        confirmations.append(c)
                    case .done:
                        break
                    case .error(let message):
                        error = message
                    }
                }
            } catch is CancellationError {
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    /// Stopp-Taste: anders als Weggehen soll der Server die Antwort wirklich abbrechen.
    private func stop() {
        streamTask?.cancel()
        runningInBackground = false
        Task { try? await model.client.send("/api/chat/threads/\(thread.id)/stop") }
    }

    private func confirm(_ c: PendingConfirmation, approved: Bool) {
        Task {
            do {
                let result: ConfirmResult = try await model.client.post(
                    "/api/chat/confirm", body: ["action_id": JSONValue.string(c.actionId), "approved": .bool(approved)])
                confirmations.removeAll { $0.id == c.id }
                guard result.success else { error = result.message; return }
                messages.append(ChatMessage(role: .other, content: approved ? "✓ \(result.message.isEmpty ? c.summary : result.message)" : "✕ Abgelehnt: \(c.summary)"))
                model.reloadAll()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}

private struct MessageView: View {
    var message: ChatMessage

    var body: some View {
        switch message.role {
        case .user:
            HStack {
                Spacer(minLength: 48)
                Text(message.content)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(Theme.accent, in: .rect(cornerRadius: 18))
                    .foregroundStyle(.white)
                    .textSelection(.enabled)
            }
        case .assistant:
            MarkdownText(text: message.content)
                .font(.callout)
        case .toolUse:
            if let tool = message.tool {
                Label {
                    Text(tool.label + (tool.input.isEmpty ? "" : " · " + tool.input.values.prefix(2).map(\.display).joined(separator: ", ")))
                        .lineLimit(1)
                } icon: {
                    Image(systemName: "wrench.and.screwdriver")
                }
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(.background.secondary, in: .capsule)
            }
        case .other:
            Text(message.content).font(.caption).foregroundStyle(.secondary)
                .frame(maxWidth: .infinity)
        }
    }
}

private struct ConfirmationCard: View {
    var confirmation: PendingConfirmation
    var decide: (Bool) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Velora braucht dein OK", systemImage: "hand.raised.fill")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Theme.amber)
            Text(confirmation.summary).font(.subheadline)
            if !confirmation.params.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(confirmation.params.sorted { $0.key < $1.key }, id: \.key) { key, value in
                        Text("\(key): \(value.display)").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            HStack {
                Button("Ablehnen", role: .cancel) { decide(false) }
                    .buttonStyle(.bordered)
                Button("Bestätigen") { decide(true) }
                    .buttonStyle(.borderedProminent)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.amber.opacity(0.1), in: .rect(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Theme.amber.opacity(0.4)))
    }
}
