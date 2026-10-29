import SwiftUI
import VeloraKit

@main
struct VeloraApp: App {
    @UIApplicationDelegateAdaptor private var delegate: AppDelegate
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(delegate.model)
                .preferredColorScheme(.dark)
                .task { await delegate.model.setUpNotifications() }
                .onChange(of: scenePhase) { old, phase in
                    // Nach längerer Pause im Hintergrund aktuelle Daten holen – und nachsehen,
                    // ob Mitteilungen in den iOS-Einstellungen inzwischen erlaubt wurden.
                    if old == .background, phase == .active {
                        delegate.model.reloadAll()
                        Task { await delegate.model.setUpNotifications() }
                    }
                }
        }
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        TabView(selection: $model.selectedTab) {
            Tab("Übersicht", systemImage: "chart.pie.fill", value: AppTab.dashboard) { DashboardView() }
            Tab("Depot", systemImage: "briefcase.fill", value: AppTab.portfolio) { PortfolioView() }
            Tab("Markt", systemImage: "globe.europe.africa.fill", value: AppTab.market) { MarketView() }
            Tab("Berater", systemImage: "doc.text.magnifyingglass", value: AppTab.advisor) { AdvisorView() }
                .badge(model.actionableCount)
            Tab("Chat", systemImage: "bubble.left.and.text.bubble.right.fill", value: AppTab.chat) { ChatListView() }
        }
    }
}
