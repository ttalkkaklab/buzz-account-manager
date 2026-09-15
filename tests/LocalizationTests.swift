import Foundation

@main struct LocalizationTests {
    static func main() {
        let original = UserDefaults.standard.object(forKey: "displayLanguage")
        defer {
            if let original = original { UserDefaults.standard.set(original, forKey: "displayLanguage") }
            else { UserDefaults.standard.removeObject(forKey: "displayLanguage") }
        }
        assert(AppLanguage.resolve("system", preferred: ["vi-VN", "en-US"]) == "vi")
        assert(AppLanguage.resolve("system", preferred: ["fr-FR"]) == "en")
        assert(AppLanguage.resolve("ko", preferred: ["en-US"]) == "ko")
        assert(AppLanguage.translations.count > 180)
        for (key, values) in AppLanguage.translations {
            for language in ["en", "vi"] {
                guard let translated = values[language], !translated.isEmpty else { fatalError("Missing \(language): \(key)") }
                let regex = try! NSRegularExpression(pattern: #"\{[0-9]+\}|%\.1f%%"#)
                func tokens(_ value: String) -> [String] {
                    regex.matches(in: value, range: NSRange(value.startIndex..., in: value)).map { String(value[Range($0.range, in: value)!]) }.sorted()
                }
                assert(tokens(key) == tokens(translated), "Placeholder mismatch: \(key)")
            }
        }
        for language in ["ko", "en", "vi"] {
            UserDefaults.standard.set(language, forKey: "displayLanguage")
            let custom = "특급개발자 {0} / Work"
            assert(L("예비 {0}", custom).contains(custom))
            assert(localizedBackend(custom + ": 예비 계정으로 전환했습니다.").hasPrefix(custom))
            assert(localizedBackend("Unrecognized provider output") == "Unrecognized provider output")
            assert(!displayDate(Date()).isEmpty)
        }
        UserDefaults.standard.set("vi", forKey: "displayLanguage")
        assert(L("자세히 보기") == "Xem chi tiết")
        assert(localizedQuotaLabel("Codex · 5시간") == "Codex · 5 giờ")
        assert(localizedQuotaLabel("Claude Code · 7일") == "Claude Code · 7 ngày")
        assert(localizedBackend("gpt-reserve 크레딧: 42") == "gpt-reserve tín dụng: 42")
        UserDefaults.standard.set("en", forKey: "displayLanguage")
        assert(L("구독 계정") == "Subscription accounts")
        assert(localizedBackend("계정이 없습니다. 새로고침해 주세요.") == "Account not found. Please refresh.")
        print("Localization tests passed: \(AppLanguage.translations.count) entries, 3 languages")
    }
}
