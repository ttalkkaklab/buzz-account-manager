import Foundation

@main struct LoginParsingTests {
    @MainActor static func main() {
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
