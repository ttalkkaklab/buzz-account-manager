import Foundation

@main struct LoginParsingTests {
    @MainActor static func main() {
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try! FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: temp) }
        let broken = temp.appendingPathComponent("broken-python")
        let working = temp.appendingPathComponent("working-python")
        try! "#!/bin/sh\nexit 69\n".write(to: broken, atomically: true, encoding: .utf8)
        try! "#!/bin/sh\nexit 0\n".write(to: working, atomically: true, encoding: .utf8)
        for path in [broken, working] {
            try! FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: path.path)
        }
        assert(try! pythonExecutable(candidates: [broken.path, working.path]) == working.path)
        do {
            _ = try pythonExecutable(candidates: [broken.path])
            assertionFailure("Unavailable Python must report an error")
        } catch {}
        print("Python runtime selection tests passed")
        let app = AppModel()
        app.loginAccount = Account(id: "test", name: "test", provider: "codex", home: "/tmp/test", builtin: false, ready: false, models: [])
        app.loginRunning = true
        app.appendLoginChunk("BUZZ_LO")
        assert(app.loginCode == nil)
        app.appendLoginChunk("GIN:{\"code\":\"ABCD-EFGH\",\"url\":\"https://auth.openai.com/codex/device\"}\r\n")
        assert(app.loginCode?.code == "ABCD-EFGH", "PTY CRLF must be recognized as a line ending")
        assert(!app.loginOutput.contains("ABCD-EFGH"), "Code belongs in its dedicated field")
        app.loginCode = nil
        app.appendLoginChunk("BUZZ_LOGIN:{\"code\":\"IJKL-MNOP\",\"url\":\"https://auth.openai.com/codex/device\"}\r")
        app.appendLoginChunk("\n")
        assert(app.loginCode?.code == "IJKL-MNOP", "Split CRLF must be handled")
        app.loginCode = nil
        app.loginRunning = false
        app.appendLoginChunk("BUZZ_LOGIN:{\"code\":\"OLD-CODE\",\"url\":\"https://auth.openai.com/codex/device\"}\n")
        assert(app.loginCode == nil, "A late chunk must not restore an expired code")
        print("Login stream tests passed")
    }
}
