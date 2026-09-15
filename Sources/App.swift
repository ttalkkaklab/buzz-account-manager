import SwiftUI
import AppKit

struct ModelChoice: Codable, Identifiable {
    var id: String
    var name: String
    var efforts: [String]
    var default_effort: String
}
struct UsageWindow: Codable {
    var label: String
    var remaining_percent: Double
    var resets_at: String?
    var is_primary: Bool? = nil
}
struct AccountUsage: Codable {
    var account_id: String
    var windows: [UsageWindow]
    var notes: [String]
    var checked_at: String
    var status: String
    var message: String
}
struct LoginCode: Codable {
    var code: String
    var url: String
}
struct Account: Codable, Identifiable {
    var id: String
    var name: String
    var provider: String
    var home: String
    var builtin: Bool
    var ready: Bool
    var models: [ModelChoice]
    var endpoint: String? = nil
}
struct Agent: Codable, Identifiable {
    var id: String
    var name: String
    var provider: String
    var model: String
    var effort: String
    var account_id: String
    var fallback_ids: [String]? = nil
    var auto_fallback: Bool? = nil
}
struct MonitorState: Codable {
    var checked_at: String?
    var usages: [String: AccountUsage]?
    var last_events: [String]?
}
struct Snapshot: Codable {
    var revision: String
    var agents: [Agent]
    var accounts: [Account]
    var cli_available: [String: Bool]
    var monitor: MonitorState? = nil
}
struct AppFailure: LocalizedError {
    var message: String
    var errorDescription: String? { localizedBackend(message) }
}
func providerName(_ id: String) -> String {
    ["codex": "Codex", "claude": "Claude Code", "grok": "Grok", "ollama": "Ollama"][id] ?? id
}
func providerColor(_ id: String) -> Color {
    ["codex": Color(red: 0.15, green: 0.50, blue: 0.43), "claude": Color(red: 0.76, green: 0.43, blue: 0.31), "grok": Color(red: 0.33, green: 0.42, blue: 0.70)][id] ?? .accentColor
}
func helperPath() -> String { Bundle.main.path(forResource: "backend", ofType: "py")! }
func processEnvironment() -> [String: String] {
    var env = ProcessInfo.processInfo.environment
    env["PATH"] = NSHomeDirectory() + "/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    env["PYTHONUNBUFFERED"] = "1"
    return env
}
func callBackend(_ action: String, payload: [String: String]? = nil) async throws -> Data {
    try await withCheckedThrowingContinuation { continuation in
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let task = Process()
                task.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
                task.arguments = [helperPath(), action]
                task.environment = processEnvironment()
                let output = Pipe(), input = Pipe()
                task.standardOutput = output
                task.standardError = FileHandle.nullDevice
                task.standardInput = input
                try task.run()
                if let payload = payload { input.fileHandleForWriting.write(try JSONSerialization.data(withJSONObject: payload)) }
                try input.fileHandleForWriting.close()
                let data = output.fileHandleForReading.readDataToEndOfFile()
                task.waitUntilExit()
                if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let error = obj["error"] as? String {
                    throw AppFailure(message: error)
                }
                guard task.terminationStatus == 0 else { throw AppFailure(message: L("설정을 읽지 못했습니다. 다시 시도해 주세요.")) }
                continuation.resume(returning: data)
            } catch { continuation.resume(throwing: error) }
        }
    }
}

@MainActor final class AppModel: ObservableObject {
    @Published var snapshot: Snapshot?
    @Published var selection = ""
    @Published var busy = false
    @Published var message = ""
    @Published var error = ""
    @Published var accountSheet = false
    @Published var loginAccount: Account?
    @Published var loginOutput = ""
    @Published var loginRunning = false
    @Published var loginCode: LoginCode?
    @Published var usage: [String: AccountUsage] = [:]
    @Published var usageLoading = Set<String>()
    private var loginLineBuffer = ""
    private var usageGeneration: [String: Int] = [:]
    private var loginProcess: Process?
    private var loginInput: Pipe?
    private var monitorTimer: Timer?
    private var terminateObserver: NSObjectProtocol?

    init() {
        #if !TESTING
        Task {
            do { _ = try await callBackend("install-monitor") }
            catch { self.error = L("자동 조회를 시작하지 못했습니다. ") + error.localizedDescription }
        }
        monitorTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self = self, !self.busy, !self.loginRunning else { return }
                if let data = try? await callBackend("status"), let latest = try? JSONDecoder().decode(Snapshot.self, from: data) {
                    self.snapshot = latest
                    for (id, value) in latest.monitor?.usages ?? [:] {
                        if value.checked_at > (self.usage[id]?.checked_at ?? "") { self.usage[id] = value }
                    }
                }
            }
        }
        #endif
        terminateObserver = NotificationCenter.default.addObserver(forName: NSApplication.willTerminateNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated {
                self?.loginInput?.fileHandleForWriting.write(Data([3]))
                if let task = self?.loginProcess, task.isRunning { task.terminate() }
            }
        }
    }

    func refresh() async {
        busy = true
        defer { busy = false }
        do {
            snapshot = try JSONDecoder().decode(Snapshot.self, from: await callBackend("status"))
            if selection.isEmpty { selection = snapshot?.agents.first?.id ?? "accounts" }
        } catch { self.error = error.localizedDescription }
    }
    func refreshUsage(_ id: String) async {
        guard !usageLoading.contains(id), !(loginRunning && loginAccount?.id == id) else { return }
        usageLoading.insert(id)
        let generation = usageGeneration[id, default: 0]
        defer {
            usageLoading.remove(id)
            if generation != usageGeneration[id, default: 0] && !(loginRunning && loginAccount?.id == id) {
                Task { await refreshUsage(id) }
            }
        }
        do {
            let result = try JSONDecoder().decode(AccountUsage.self, from: await callBackend("usage", payload: ["account_id": id]))
            guard generation == usageGeneration[id, default: 0], !(loginRunning && loginAccount?.id == id) else { return }
            usage[id] = result
        } catch {
            guard generation == usageGeneration[id, default: 0] else { return }
            usage[id] = AccountUsage(account_id: id, windows: [], notes: [], checked_at: ISO8601DateFormatter().string(from: Date()),
                                     status: "unavailable", message: L("잔량을 조회하지 못했습니다. 다시 조회하세요."))
        }
    }
    func refreshAllUsage() {
        for account in snapshot?.accounts ?? [] {
            Task { await refreshUsage(account.id) }
        }
    }
    func appendLoginChunk(_ chunk: String) {
        loginLineBuffer += chunk.replacingOccurrences(of: "\r\n", with: "\n").replacingOccurrences(of: "\r", with: "\n")
        while let end = loginLineBuffer.firstIndex(of: "\n") {
            let line = String(loginLineBuffer[..<end]).trimmingCharacters(in: .newlines)
            loginLineBuffer = String(loginLineBuffer[loginLineBuffer.index(after: end)...])
            if line.hasPrefix("BUZZ_LOGIN:"), let data = String(line.dropFirst(11)).data(using: .utf8),
               let value = try? JSONDecoder().decode(LoginCode.self, from: data) {
                if loginRunning { loginCode = value }
                loginOutput += (L("로그인 코드가 준비됐습니다. 아래 코드를 로그인 페이지에 입력하세요.") + "\n")
            } else {
                loginOutput += localizedBackend(line) + "\n"
            }
        }
        // Other CLIs can write an input prompt without a trailing newline.
        if loginAccount?.provider != "codex" && !loginLineBuffer.isEmpty {
            loginOutput += loginLineBuffer
            loginLineBuffer = ""
        }
        if loginOutput.count > 24000 { loginOutput = String(loginOutput.suffix(24000)) }
    }
    func create(name: String, provider: String, endpoint: String = "") async {
        busy = true
        do {
            let data = try await callBackend("create", payload: ["name": name, "provider": provider, "endpoint": endpoint])
            let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            accountSheet = false
            await refresh()
            if let id = object?["id"] as? String, let a = snapshot?.accounts.first(where: { $0.id == id }) {
                if provider == "ollama" { selection = "accounts"; await refreshUsage(a.id) }
                else { startLogin(a) }
            }
        } catch { self.error = error.localizedDescription }
        busy = false
    }
    func startLogin(_ account: Account) {
        guard !loginRunning, account.provider != "ollama" else { return }
        loginAccount = account
        usageGeneration[account.id, default: 0] += 1
        usage.removeValue(forKey: account.id)
        loginCode = nil
        loginLineBuffer = ""
        loginOutput = (L("로그인 절차를 시작합니다. 브라우저에서 사용할 계정을 확인해 주세요.") + "\n")
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/script")
        task.arguments = ["-q", "/dev/null", "/usr/bin/python3", helperPath(), "login", account.id]
        task.environment = processEnvironment()
        let output = Pipe(), input = Pipe()
        task.standardOutput = output
        task.standardError = output
        task.standardInput = input
        loginInput = input
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let bytes = handle.availableData
            if bytes.isEmpty { handle.readabilityHandler = nil; return }
            let chunk = String(decoding: bytes, as: UTF8.self)
                .replacingOccurrences(of: "\u{001B}\\[[0-9;?]*[ -/]*[@-~]", with: "", options: .regularExpression)
            Task { @MainActor [weak self] in
                guard let self = self else { return }
                self.appendLoginChunk(chunk)
            }
        }
        task.terminationHandler = { [weak self] process in
            Task { @MainActor [weak self] in
                guard let self = self else { return }
                self.loginRunning = false
                self.loginCode = nil
                self.loginProcess = nil
                self.loginInput = nil
                self.loginOutput += process.terminationStatus == 0 ? ("\n" + L("로그인 절차가 끝났습니다. 저장된 인증정보를 확인합니다.") + "\n") : ("\n" + L("로그인이 종료됐습니다. 다시 시도하거나 창을 닫으세요.") + "\n")
                await self.refresh()
                await self.refreshUsage(account.id)
            }
        }
        do {
            try task.run()
            loginProcess = task
            loginRunning = true
        } catch { self.error = error.localizedDescription; loginRunning = false }
    }
    func cancelLogin() {
        // Ctrl-C goes through the PTY to the foreground CLI and its browser callback server.
        loginInput?.fileHandleForWriting.write(Data([3]))
        if let task = loginProcess {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
                if task.isRunning { task.terminate() }
            }
        }
    }
    func sendLoginInput(_ text: String) {
        loginInput?.fileHandleForWriting.write(Data((text + "\n").utf8))
    }
    func apply(agent: Agent, account: String, provider: String, model: String, effort: String, revision: String, fallbackIDs: [String], autoFallback: Bool) async {
        busy = true
        message = L("로그인과 모델 설정을 확인하는 중…")
        do {
            let payload = ["agent_id": agent.id, "account_id": account, "provider": provider,
                           "model": model, "effort": effort, "revision": revision,
                           "fallback_ids": String(data: try JSONEncoder().encode(fallbackIDs), encoding: .utf8)!,
                           "auto_fallback": autoFallback ? "true" : "false", "expected_account_id": agent.account_id]
            _ = try await callBackend("validate", payload: payload)
            let running = NSWorkspace.shared.runningApplications.filter { $0.bundleURL?.path == "/Applications/Buzz.app" }
            if !running.isEmpty {
                message = L("Buzz를 정상 종료하는 중…")
                for app in running { guard app.terminate() else { throw AppFailure(message: L("Buzz를 종료하지 못했습니다. 직접 종료한 뒤 다시 적용하세요.")) } }
                for _ in 0..<100 {
                    if running.allSatisfy({ $0.isTerminated }) { break }
                    try await Task.sleep(nanoseconds: 100_000_000)
                }
                guard running.allSatisfy({ $0.isTerminated }) else { throw AppFailure(message: L("Buzz가 아직 종료되지 않았습니다. 설정은 변경하지 않았습니다.")) }
            }
            message = L("설정을 백업하고 저장하는 중…")
            _ = try await callBackend("apply", payload: payload)
            message = L("{0} 설정을 저장했습니다. Buzz는 직접 시작하세요.", String(describing: agent.name))
            await refresh()
        } catch {
            self.error = error.localizedDescription
            message = ""
        }
        busy = false
    }
}

struct ProviderBadge: View {
    var provider: String
    var body: some View {
        Text(providerName(provider)).font(.system(size: 11, weight: .semibold))
            .padding(.horizontal, 9).padding(.vertical, 4)
            .foregroundStyle(providerColor(provider))
            .background(providerColor(provider).opacity(0.10), in: Capsule())
    }
}
struct ContentView: View {
    @StateObject var app = AppModel()
    @AppStorage("displayLanguage") private var displayLanguage = "system"
    var body: some View {
        NavigationSplitView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 10) {
                    Image("AppIcon").resizable().interpolation(.high).frame(width: 36, height: 36).accessibilityLabel(L("딸깍맨"))
                    VStack(alignment: .leading, spacing: 3) {
                        Text(L("Buzz 계정 관리")).font(.headline)
                        Text(L("이 Mac의 에이전트")).font(.caption).foregroundStyle(.secondary)
                    }
                }.padding(22)
                List(selection: $app.selection) {
                    Section(L("에이전트")) {
                        ForEach(app.snapshot?.agents ?? []) { agent in
                            HStack(spacing: 10) {
                                Image(systemName: "person.crop.circle.fill").font(.title2).foregroundStyle(providerColor(agent.provider))
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(agent.name).font(.system(size: 13, weight: .medium))
                                    Text(providerName(agent.provider)).font(.caption).foregroundStyle(.secondary)
                                }
                            }.padding(.vertical, 6).tag(agent.id)
                        }
                    }
                    Section {
                        Label(L("구독 계정"), systemImage: "key.horizontal").padding(.vertical, 8).tag("accounts")
                    }
                }.listStyle(.sidebar)
                Divider()
                HStack {
                    Label(L("로컬 설정"), systemImage: "internaldrive").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button { Task { await app.refresh() } } label: { Image(systemName: "arrow.clockwise") }
                        .buttonStyle(.plain).help(L("새로고침")).disabled(app.busy)
                }.padding(18)
                Picker(L("언어"), selection: $displayLanguage) {
                    Text(L("시스템 설정")).tag("system")
                    Text("한국어").tag("ko")
                    Text("English").tag("en")
                    Text("Tiếng Việt").tag("vi")
                }.padding(.horizontal, 18).padding(.bottom, 18)
            }.navigationSplitViewColumnWidth(min: 220, ideal: 245, max: 290)
        } detail: {
            if let snapshot = app.snapshot {
                if app.selection == "accounts" {
                    AccountsView(app: app, accounts: snapshot.accounts)
                } else if let agent = snapshot.agents.first(where: { $0.id == app.selection }) {
                    AgentEditor(app: app, agent: agent, snapshot: snapshot).id(agent.id + snapshot.revision + agent.account_id)
                } else {
                    ContentUnavailableView(L("에이전트를 선택하세요"), systemImage: "person.crop.circle", description: Text(L("Buzz에 등록된 에이전트가 왼쪽에 표시됩니다.")))
                }
            } else {
                VStack(spacing: 14) {
                    if app.busy { ProgressView() }
                    Text(app.busy ? L("Buzz 설정을 읽는 중…") : L("Buzz 설정을 불러오세요.")).foregroundStyle(.secondary)
                    Button(L("새로고침")) { Task { await app.refresh() } }
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .environment(\.locale, Locale(identifier: AppLanguage.resolve(displayLanguage)))
        .frame(minWidth: 1000, minHeight: 720)
        .task { await app.refresh() }
        .onChange(of: displayLanguage) { _, _ in
            for window in NSApplication.shared.windows where window.sheetParent == nil {
                window.title = L("Buzz 계정 관리")
            }
        }
        .sheet(isPresented: $app.accountSheet) { AddAccountView(app: app) }
        .sheet(item: $app.loginAccount) { account in LoginView(app: app, account: account).interactiveDismissDisabled(app.loginRunning) }
        .alert(L("설정을 확인해 주세요"), isPresented: Binding(get: { !app.error.isEmpty }, set: { if !$0 { app.error = "" } })) {
            Button(L("확인")) { app.error = "" }
        } message: { Text(localizedBackend(app.error)) }
    }
}
struct AgentEditor: View {
    @Environment(\.locale) private var displayLocale
    @ObservedObject var app: AppModel
    let agent: Agent
    let snapshot: Snapshot
    @State var provider: String
    @State var accountID: String
    @State var model: String
    @State var effort: String
    @State var fallbackIDs: [String]
    @State var autoFallback: Bool
    @State var customModel = false

    init(app: AppModel, agent: Agent, snapshot: Snapshot) {
        self.app = app; self.agent = agent; self.snapshot = snapshot
        _provider = State(initialValue: agent.provider)
        _accountID = State(initialValue: agent.account_id)
        _model = State(initialValue: agent.model)
        _effort = State(initialValue: agent.effort)
        _fallbackIDs = State(initialValue: Array((agent.fallback_ids ?? []) + Array(repeating: "", count: 3)).prefix(3).map { $0 })
        _autoFallback = State(initialValue: agent.auto_fallback ?? false)
        let choices = snapshot.accounts.first(where: { $0.id == agent.account_id })?.models ?? []
        _customModel = State(initialValue: !choices.contains(where: { $0.id == agent.model }))
    }
    var currentAccountName: String {
        guard let current = snapshot.accounts.first(where: { $0.id == agent.account_id }) else { return L("계정 등록 필요") }
        return current.builtin ? L(current.name) : current.name
    }
    var accounts: [Account] { snapshot.accounts.filter { $0.provider == provider } }
    var account: Account? { accounts.first { $0.id == accountID } }
    var choices: [ModelChoice] { account?.models ?? accounts.first?.models ?? [] }
    var efforts: [String] { if provider == "ollama" { return [] }; return choices.first(where: { $0.id == model })?.efforts ?? ["low", "medium", "high", "xhigh", "max", "ultra"] }
    var body: some View {
        let _ = displayLocale
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(agent.name).font(.system(size: 28, weight: .bold))
                        Text(L("구독 계정과 생각의 깊이를 선택하세요.")).foregroundStyle(.secondary)
                    }
                    Spacer()
                    ProviderBadge(provider: agent.provider)
                }
                HStack(spacing: 9) {
                    Image(systemName: "checkmark.shield").foregroundStyle(.teal)
                    Text(L("이름 · Buzz 신원 · 팀은 그대로 유지합니다.")).font(.callout).foregroundStyle(.secondary)
                }
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(L("현재 구독 계정 잔량")).font(.headline)
                            Text(currentAccountName)
                                .font(.callout).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button(L("잔량 새로고침")) { Task { await app.refreshUsage(agent.account_id) } }
                            .disabled(app.usageLoading.contains(agent.account_id))
                    }
                    UsageView(usage: app.usage[agent.account_id] ?? snapshot.monitor?.usages?[agent.account_id],
                              loading: app.usageLoading.contains(agent.account_id))
                }
                .padding(24)
                .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 16))
                .task(id: agent.account_id) { if app.usage[agent.account_id] == nil { await app.refreshUsage(agent.account_id) } }
                VStack(alignment: .leading, spacing: 22) {
                    fieldTitle("01", L("AI 서비스"))
                    Picker(L("AI 서비스"), selection: $provider) {
                        ForEach(["codex", "claude", "grok", "ollama"], id: \.self) { Text(providerName($0)).tag($0) }
                    }.pickerStyle(.segmented).labelsHidden()
                        .onChange(of: provider) { _, _ in
                            fallbackIDs = ["", "", ""]
                            autoFallback = false
                            accountID = accounts.first?.id ?? ""
                            model = choices.first?.id ?? ""
                            effort = choices.first?.default_effort ?? ""
                            customModel = choices.isEmpty
                        }
                    Divider()
                    fieldTitle("02", provider == "ollama" ? L("Ollama 서버") : L("구독 계정"))
                    HStack {
                        Picker(L("구독 계정"), selection: $accountID) {
                            if accountID == "unregistered" { Text(L("기존 경로: 계정 등록 필요")).tag("unregistered") }
                            ForEach(accounts) { item in Text(item.builtin ? L(item.name) : item.name).tag(item.id) }
                        }.labelsHidden().controlSize(.large)
                            .onChange(of: accountID) { _, _ in
                                fallbackIDs = fallbackIDs.map { $0 == accountID ? "" : $0 }
                                if provider == "ollama" || (!customModel && !choices.contains(where: { $0.id == model })) {
                                    model = choices.first?.id ?? ""
                                    effort = choices.first?.default_effort ?? ""
                                    customModel = false
                                }
                            }
                        Button { app.accountSheet = true } label: { Label(L("계정 추가"), systemImage: "plus") }
                    }
                    if let account = account {
                        Label(provider == "ollama" ? (account.ready ? L("Ollama 서버에 연결됐습니다.") : L("Ollama 서버를 실행하거나 서버 주소를 추가하세요.")) : (account.ready ? L("저장된 로그인 정보가 있습니다.") : L("계정 탭에서 먼저 로그인하세요.")),
                              systemImage: account.ready ? "checkmark.circle.fill" : "person.crop.circle.badge.exclamationmark")
                            .font(.caption).foregroundStyle(account.ready ? Color.secondary : Color.orange)
                    }
                    if provider == "ollama" {
                        Text(account?.endpoint ?? "http://127.0.0.1:11434").font(.caption).foregroundStyle(.secondary)
                        Text(L("도구 호출을 지원하는 로컬 모델을 사용합니다. 모델을 설치한 뒤 왼쪽 아래 새로고침을 누르세요."))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    Divider()
                    if provider == "codex" || provider == "claude" {
                        VStack(alignment: .leading, spacing: 12) {
                            Text(L("예비 구독 계정 · 최대 3개")).font(.headline)
                            ForEach(0..<3, id: \.self) { index in
                                Picker(L("예비 {0}", String(describing: index + 1)), selection: $fallbackIDs[index]) {
                                    Text(L("선택 안 함")).tag("")
                                    ForEach(accounts.filter { $0.id != accountID && (!fallbackIDs.contains($0.id) || fallbackIDs[index] == $0.id) }) { item in
                                        Text((item.builtin ? L(item.name) : item.name) + (item.ready ? "" : L(" · 로그인 필요"))).tag(item.id)
                                    }
                                }
                            }
                            Toggle(L("한도 소진 시 예비 계정으로 자동 전환"), isOn: $autoFallback)
                            Text(L("5분마다 잔량을 조회하고 위 순서대로 전환합니다. 모델과 effort는 유지합니다. 조회 실패 시에는 전환하지 않습니다."))
                                .font(.caption).foregroundStyle(.secondary)
                            Text(L("앱을 닫아도 로그인한 Mac에서 동작합니다. 계정을 전환하면 실행 중인 Buzz를 종료합니다. Buzz는 직접 시작하세요."))
                                .font(.caption).foregroundStyle(.orange)
                            if let checked = snapshot.monitor?.checked_at, let date = usageDate(checked) {
                                Text(L("자동 조회: {0}", String(describing: displayDate(date, timeOnly: true)))).font(.caption).foregroundStyle(.secondary)
                            }
                            ForEach(snapshot.monitor?.last_events ?? [], id: \.self) { Text(localizedBackend($0)).font(.caption).foregroundStyle(.secondary) }
                        }
                        Divider()
                    }
                    fieldTitle("03", L("모델"))
                    if provider == "ollama" && choices.isEmpty {
                        Text(L("사용할 로컬 모델이 없습니다. Ollama 서버에 도구 호출을 지원하는 모델을 설치하고 새로고침하세요."))
                            .font(.callout).foregroundStyle(.secondary)
                    } else if !customModel && !choices.isEmpty {
                        Picker(L("모델"), selection: $model) {
                            ForEach(choices) { Text($0.name + "  ·  " + $0.id).tag($0.id) }
                        }.labelsHidden().controlSize(.large)
                    } else {
                        TextField(L("모델 ID"), text: $model).textFieldStyle(.roundedBorder).controlSize(.large)
                    }
                    HStack {
                        Toggle(L("모델 ID 직접 입력"), isOn: $customModel).toggleStyle(.checkbox).disabled(provider == "ollama")
                        Spacer()
                        Text(provider == "ollama" ? L("Ollama 설치 모델") : provider == "claude" ? L("CLI 모델 별칭") : L("로컬 모델 캐시")).font(.caption).foregroundStyle(.tertiary)
                    }
                    .onChange(of: customModel) { _, custom in
                        if !custom && !choices.contains(where: { $0.id == model }) { model = choices.first?.id ?? "" }
                    }
                    .onChange(of: model) { _, _ in
                        if !effort.isEmpty && !efforts.contains(effort) { effort = "" }
                    }
                    Divider()
                    fieldTitle("04", L("Effort"))
                    Picker(L("Effort"), selection: $effort) {
                        Text(L("모델 기본값")).tag("")
                        ForEach(efforts, id: \.self) { Text($0).tag($0) }
                    }.pickerStyle(.segmented).labelsHidden()
                    Text(provider == "ollama" ? L("Ollama는 모델의 기본 추론 설정을 사용합니다. 구독 계정의 사용량은 차감하지 않습니다.") : L("높을수록 더 오래 생각하며 구독 사용량이 늘 수 있습니다. 지원 범위는 모델마다 다릅니다."))
                        .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                .padding(24)
                .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 16))
                .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.primary.opacity(0.06)))
                HStack(alignment: .center, spacing: 20) {
                    VStack(alignment: .leading, spacing: 5) {
                        Text(L("설정은 즉시 저장됩니다. Buzz는 직접 시작하세요.")).font(.callout).fontWeight(.medium)
                        Text(L("실행 중인 Buzz는 종료되며 모든 에이전트의 응답이 중단될 수 있습니다.")).font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button {
                        Task { await app.apply(agent: agent, account: accountID, provider: provider, model: model, effort: effort, revision: snapshot.revision, fallbackIDs: fallbackIDs.filter { !$0.isEmpty }, autoFallback: autoFallback) }
                    } label: {
                        HStack(spacing: 8) {
                            if app.busy { ProgressView().controlSize(.small) }
                            Text(L("설정 저장"))
                        }
                    }.buttonStyle(.borderedProminent).tint(.teal).controlSize(.large)
                        .disabled(app.busy || account?.ready != true || model.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                if !app.message.isEmpty { Text(app.message).font(.callout).foregroundStyle(.secondary).textSelection(.enabled) }
            }.padding(32).frame(maxWidth: 890)
        }.frame(maxWidth: .infinity, maxHeight: .infinity).background(Color(nsColor: .windowBackgroundColor))
    }
    func fieldTitle(_ number: String, _ title: String) -> some View {
        HStack(spacing: 10) {
            Text(number).font(.system(size: 11, weight: .bold, design: .monospaced)).foregroundStyle(.teal)
            Text(title).font(.headline)
        }
    }
}
struct AccountsView: View {
    @Environment(\.locale) private var displayLocale
    @ObservedObject var app: AppModel
    var accounts: [Account]
    var body: some View {
        let _ = displayLocale
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                HStack {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(L("구독 계정")).font(.system(size: 28, weight: .bold))
                        Text(L("서비스마다 여러 계정을 등록하고 에이전트에 연결하세요.")).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button(L("잔량 새로고침")) { app.refreshAllUsage() }.disabled(!app.usageLoading.isEmpty)
                    Button { app.accountSheet = true } label: { Label(L("계정 추가"), systemImage: "plus") }
                        .buttonStyle(.borderedProminent).tint(.teal).controlSize(.large)
                }
                ForEach(["codex", "claude", "grok", "ollama"], id: \.self) { provider in
                    VStack(alignment: .leading, spacing: 14) {
                        HStack { ProviderBadge(provider: provider); Spacer() }
                        ForEach(accounts.filter { $0.provider == provider }) { account in
                            VStack(alignment: .leading, spacing: 12) {
                            HStack(spacing: 14) {
                                Image(systemName: account.builtin ? "laptopcomputer" : "person.crop.circle")
                                    .font(.title2).foregroundStyle(.secondary).frame(width: 32)
                                VStack(alignment: .leading, spacing: 5) {
                                    Text(account.builtin ? L(account.name) : account.name).font(.headline)
                                    Text(account.provider == "ollama" ? (account.ready ? L("서버 연결됨") : L("서버 연결 필요")) : (account.ready ? L("로그인 정보 있음") : L("로그인 필요")))
                                        .font(.caption).foregroundStyle(account.ready ? Color.secondary : Color.orange)
                                    Text(account.endpoint ?? account.home.replacingOccurrences(of: NSHomeDirectory(), with: "~"))
                                        .font(.system(size: 10, design: .monospaced)).foregroundStyle(.tertiary).textSelection(.enabled)
                                }
                                Spacer()
                                if account.provider == "ollama" {
                                    Button(L("연결 확인")) { Task { await app.refresh(); await app.refreshUsage(account.id) } }.disabled(app.busy)
                                } else if !account.builtin {
                                    Button(account.ready ? L("다시 로그인") : L("로그인")) { app.startLogin(account) }.disabled(app.loginRunning)
                                } else {
                                    Text(L("기본 계정")).font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            UsageView(usage: app.usage[account.id], loading: app.usageLoading.contains(account.id))
                            Button(L("이 계정 잔량 새로고침")) { Task { await app.refreshUsage(account.id) } }
                                .font(.caption)
                                .disabled(app.usageLoading.contains(account.id) || (app.loginRunning && app.loginAccount?.id == account.id))
                            }.padding(.vertical, 9)
                            .task { if app.usage[account.id] == nil { await app.refreshUsage(account.id) } }
                        }
                    }.padding(22).background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 16))
                }
                Text(L("잔량은 서비스가 제공한 구독 한도의 남은 비율입니다. 정확한 토큰 수로 환산하지 않습니다. 조회 시각 이후의 사용량은 새로고침하면 반영됩니다."))
                    .font(.caption).foregroundStyle(.secondary)
                Label(L("새 계정은 별도 경로에 로그인합니다. 기존 CLI의 기본 계정은 변경하지 않습니다."), systemImage: "lock.shield")
                    .font(.callout).foregroundStyle(.secondary)
                Text(L("별도 계정은 CLI 설정과 세션도 분리됩니다. 로그인 만료·구독 한도·모델 접근 권한은 서비스가 실행 시 확인합니다."))
                    .font(.caption).foregroundStyle(.tertiary)
            }.padding(32).frame(maxWidth: 890)
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
func usageDate(_ value: String) -> Date? {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter.date(from: value) ?? ISO8601DateFormatter().date(from: value)
}
struct UsageView: View {
    @Environment(\.locale) private var displayLocale
    var usage: AccountUsage?
    var loading: Bool
    @State private var expanded = false
    var body: some View {
        let _ = displayLocale
        VStack(alignment: .leading, spacing: 8) {
            if loading { HStack { ProgressView().controlSize(.small); Text(L("잔량 조회 중…")).font(.caption) } }
            if let usage = usage {
                let basic = usage.windows.filter { $0.is_primary == true }
                ForEach(Array(basic.enumerated()), id: \.offset) { _, window in
                    quotaRow(window, detail: false)
                }
                if basic.isEmpty && !usage.windows.isEmpty {
                    Text(L("기본 사용 한도 정보가 없습니다.")).font(.caption).foregroundStyle(.secondary)
                }
                ForEach(usage.notes.filter { $0.contains("사용을 제한") || $0.contains("한도 도달") }, id: \.self) {
                    Text(localizedBackend($0)).font(.caption).foregroundStyle(.orange)
                }
                if !usage.message.isEmpty { Text(localizedBackend(usage.message)).font(.caption).foregroundStyle(.secondary) }
                if !usage.windows.isEmpty || !usage.notes.isEmpty {
                    DisclosureGroup(L("자세히 보기"), isExpanded: $expanded) {
                        VStack(alignment: .leading, spacing: 12) {
                            ForEach(Array(usage.windows.enumerated()), id: \.offset) { _, window in
                                quotaRow(window, detail: true)
                            }
                            ForEach(usage.notes.filter { !$0.contains("사용을 제한") && !$0.contains("한도 도달") }, id: \.self) {
                                Text(localizedBackend($0)).font(.caption).foregroundStyle(.secondary)
                            }
                        }.padding(.top, 8)
                    }.font(.caption)
                }
                if let date = usageDate(usage.checked_at) {
                    Text(L("조회 {0}", String(describing: displayDate(date)))).font(.caption2).foregroundStyle(.tertiary)
                }
            } else if !loading { Text(L("잔량 새로고침을 누르면 조회합니다.")).font(.caption).foregroundStyle(.secondary) }
        }.padding(12).background(Color.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 8))
    }
    func quotaRow(_ window: UsageWindow, detail: Bool) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(localizedQuotaLabel(window.label)).font(.caption)
                Spacer()
                Text(String(format: L("%.1f%% 남음"), window.remaining_percent)).font(.caption.monospacedDigit().bold())
            }
            ProgressView(value: window.remaining_percent, total: 100).tint(window.remaining_percent < 20 ? .orange : .teal)
            if let reset = window.resets_at, let date = usageDate(reset) {
                if date < Date() {
                    Text(L("초기화 시각이 지났습니다. 잔량을 새로고침하세요.")).font(.caption2).foregroundStyle(.secondary)
                } else if detail {
                    Text(L("초기화 {0}", String(describing: displayDate(date)))).font(.caption2).foregroundStyle(.secondary)
                }
            }
        }
    }
}
struct AddAccountView: View {
    @Environment(\.locale) private var displayLocale
    @ObservedObject var app: AppModel
    @State var name = ""
    @State var provider = "codex"
    @State var endpoint = "http://127.0.0.1:11434"
    var body: some View {
        let _ = displayLocale
        VStack(alignment: .leading, spacing: 22) {
            Text(L("구독 계정 추가")).font(.title2.bold())
            Text(L("알아보기 쉬운 이름을 붙인 뒤 서비스에 로그인하세요.")).foregroundStyle(.secondary)
            Picker(L("서비스"), selection: $provider) {
                ForEach(["codex", "claude", "grok", "ollama"], id: \.self) { Text(providerName($0)).tag($0) }
            }.pickerStyle(.segmented)
            TextField(L("예: 개인 Pro, 업무 계정"), text: $name).textFieldStyle(.roundedBorder).controlSize(.large)
            if provider == "ollama" {
                TextField(L("Ollama 서버 주소"), text: $endpoint).textFieldStyle(.roundedBorder)
                Text(L("예: http://127.0.0.1:11434 또는 맥미니의 서버 주소. 로그인과 모델 다운로드 없이 연결만 등록합니다.")).font(.caption).foregroundStyle(.secondary)
            }
            Text(L("비밀번호와 토큰은 해당 CLI가 보관합니다. 이 앱에는 직접 입력하지 않습니다.")).font(.caption).foregroundStyle(.secondary)
            HStack {
                Button(L("취소")) { app.accountSheet = false }.keyboardShortcut(.cancelAction)
                Spacer()
                Button(provider == "ollama" ? L("서버 추가") : L("추가하고 로그인")) { Task { await app.create(name: name, provider: provider, endpoint: endpoint) } }
                    .buttonStyle(.borderedProminent).tint(.teal)
                    .disabled(app.busy || name.trimmingCharacters(in: .whitespaces).isEmpty)
                    .keyboardShortcut(.defaultAction)
            }
        }.padding(30).frame(width: 550)
    }
}
struct LoginView: View {
    @Environment(\.locale) private var displayLocale
    @ObservedObject var app: AppModel
    var account: Account
    @State var input = ""
    var links: [URL] {
        let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue)
        let matches = detector?.matches(in: app.loginOutput, range: NSRange(app.loginOutput.startIndex..., in: app.loginOutput)) ?? []
        var seen = Set<String>()
        return matches.compactMap(\.url).filter { $0.scheme == "https" && seen.insert($0.absoluteString).inserted }
    }
    var body: some View {
        let _ = displayLocale
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                VStack(alignment: .leading, spacing: 6) {
                    Text(L("{0} 로그인", String(describing: providerName(account.provider)))).font(.title2.bold())
                    Text(account.builtin ? L(account.name) : account.name).foregroundStyle(.secondary)
                }
                Spacer()
                if app.loginRunning { ProgressView().controlSize(.small) }
            }
            Text(L("안내된 주소를 열고 코드를 입력하세요. 브라우저에서는 연결할 계정을 직접 선택하세요."))
                .font(.callout).foregroundStyle(.secondary)
            if account.provider == "codex" {
                VStack(alignment: .leading, spacing: 10) {
                    Text(L("로그인 페이지에 입력할 코드")).font(.headline)
                    HStack {
                        TextField(L("코드를 받는 중…"), text: .constant(app.loginCode?.code ?? ""))
                            .textFieldStyle(.roundedBorder).font(.system(size: 23, weight: .semibold, design: .monospaced))
                            .accessibilityLabel(L("Codex 로그인 코드"))
                        Button(L("복사")) {
                            if let code = app.loginCode?.code {
                                NSPasteboard.general.clearContents()
                                NSPasteboard.general.setString(code, forType: .string)
                            }
                        }.disabled(app.loginCode == nil || !app.loginRunning)
                    }
                    if let value = app.loginCode, let url = URL(string: value.url), url.scheme == "https" {
                        Button(L("로그인 페이지 열기")) { NSWorkspace.shared.open(url) }
                    }
                    Text(app.loginRunning ? L("코드를 복사한 뒤 로그인 페이지의 코드 입력란에 붙여 넣으세요.") : L("로그인이 종료됐습니다. 다시 로그인하면 새 코드를 받습니다."))
                        .font(.caption).foregroundStyle(.secondary)
                }.padding(16).background(Color.teal.opacity(0.07), in: RoundedRectangle(cornerRadius: 10))
            }
            ScrollView {
                Text(app.loginOutput).font(.system(size: 12, design: .monospaced))
                    .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(16)
            }.frame(height: 245).background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 10))
            ForEach(links.prefix(2), id: \.absoluteString) { url in
                Button { NSWorkspace.shared.open(url) } label: { Label(L("로그인 페이지 열기 · {0}", String(describing: url.host ?? "")), systemImage: "arrow.up.right.square") }
            }
            if app.loginRunning && account.provider != "codex" {
                HStack {
                    TextField(L("CLI가 코드 입력을 요청한 경우에만 입력"), text: $input).textFieldStyle(.roundedBorder)
                    Button(L("입력")) { app.sendLoginInput(input); input = "" }.disabled(input.isEmpty)
                }
            }
            HStack {
                if app.loginRunning { Button(L("로그인 취소")) { app.cancelLogin() } }
                Spacer()
                Button(L("완료 확인")) { Task { await app.refresh() } }.disabled(app.busy)
                Button(L("닫기")) { app.loginAccount = nil }.disabled(app.loginRunning).keyboardShortcut(.cancelAction)
            }
            if app.snapshot?.accounts.first(where: { $0.id == account.id })?.ready == true {
                Label(L("로그인 정보를 확인했습니다. 에이전트 화면에서 연결할 수 있습니다."), systemImage: "checkmark.circle.fill")
                    .font(.caption).foregroundStyle(.teal)
            }
        }.padding(28).frame(width: 700)
    }
}
#if !TESTING
@main struct BuzzAccountManagerApp: App {
    init() {
        NSApplication.shared.setActivationPolicy(.regular)
        if let path = Bundle.main.path(forResource: "AppIcon", ofType: "icns") {
            NSApplication.shared.applicationIconImage = NSImage(contentsOfFile: path)
        }
    }
    var body: some Scene {
        WindowGroup(L("Buzz 계정 관리")) { ContentView() }
            .defaultSize(width: 1080, height: 830)
            .commands { CommandGroup(replacing: .newItem) {} }
    }
}

#endif
