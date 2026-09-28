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
                assert(app.section == entry, "Server creation must stay in its entry screen")
                assert(!app.accountSheet && !app.busy && app.loginAccount == nil)
                assert(app.usage["created-server"]?.status == "ok", "Await the complete server creation path")
                if entry == .agents {
                    assert(app.createdAccountSelection == CreatedAccountSelection(agentID: "selected-agent", accountID: "created-server"))
                } else { assert(app.createdAccountSelection == nil) }
                app.section = .agents
                assert(app.snapshot?.agents.contains(where: { $0.id == app.selection }) == true)
                print("Server creation passed: \(provider), entry=\(entry.rawValue)")
            }
        }
        // #142 drag reorder: only the dragged service's slots move, a cancelled drag restores the list, and drops need a live drag.
        let app = AppModel()
        func account(_ id: String, _ provider: String) -> Account {
            Account(id: id, name: id, provider: provider, home: "/tmp/" + id, builtin: false, ready: true, models: [])
        }
        app.snapshot = Snapshot(revision: "fixture", agents: [], accounts: [account("A", "codex"), account("B", "claude"), account("C", "codex")], cli_available: [:])
        func ids() -> [String] { app.snapshot?.accounts.map(\.id) ?? [] }
        app.moveAccount("A", over: "C")
        assert(ids() == ["A", "B", "C"], "No move without a live drag")
        assert(app.beginDrag("A") != nil && app.draggingAccount == "A")
        assert(app.beginDrag("C") == nil && app.draggingAccount == "A", "One drag at a time")
        app.moveAccount("A", over: "B")
        assert(ids() == ["A", "B", "C"], "Another service is never a target")
        app.moveAccount("A", over: "C")
        assert(ids() == ["C", "B", "A"], "Only the Codex slots are refilled, got \(ids())")
        app.cancelDrag()
        assert(ids() == ["A", "B", "C"] && app.draggingAccount == nil, "A cancelled drag restores the order shown before it")
        assert(!app.finishDrag(), "Nothing to commit after a cancel")
        _ = app.beginDrag("C")
        app.moveAccount("C", over: "A")
        assert(ids() == ["C", "B", "A"])
        assert(app.finishDrag() && app.draggingAccount == nil)
        let sent = URL(fileURLWithPath: ProcessInfo.processInfo.environment["HOME"] ?? NSHomeDirectory()).appendingPathComponent("fixture-reorder.json")
        for _ in 0..<100 where !(FileManager.default.fileExists(atPath: sent.path) && !app.busy) {
            try? await Task.sleep(nanoseconds: 100_000_000)
        }
        let payload = (try? JSONDecoder().decode([String].self, from: Data(contentsOf: sent))) ?? []
        assert(payload == ["C", "A"], "Only the dragged service's ids are sent, got \(payload)")
        assert(app.error.isEmpty && app.message == "계정 순서를 저장했습니다.", app.error + app.message)
        print("Account drag reorder passed")
    }
}
