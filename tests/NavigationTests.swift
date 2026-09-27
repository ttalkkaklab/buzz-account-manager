import Foundation

@main struct NavigationTests {
    @MainActor static func main() async {
        for provider in ["ollama", "codex"] {
            for entry in [SettingsSection.accounts, .agents] {
                let app = AppModel()
                await app.refresh()
                assert(app.error.isEmpty)
                app.selection = "selected-agent"
                app.section = entry
                app.openAddAccount(provider: provider)
                await app.create(name: "Server", provider: provider, endpoint: "http://localhost:11434")
                assert(app.error.isEmpty, app.error)
                assert(app.snapshot?.accounts.first?.provider == provider)
                assert(app.snapshot?.accounts.first?.isServer == true)
                assert(app.selection == "selected-agent", "Server creation must preserve the selected agent")
                assert(app.section == .accounts, "Server creation must open account settings")
                assert(!app.accountSheet && !app.busy && app.loginAccount == nil)
                assert(app.usage["created-server"]?.status == "ok", "Await the complete server creation path")
                app.section = .agents
                assert(app.snapshot?.agents.contains(where: { $0.id == app.selection }) == true)
                print("Server creation passed: \(provider), entry=\(entry.rawValue)")
            }
        }
    }
}
