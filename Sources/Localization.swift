import Foundation

/// Display language is independent of provider IDs, credentials, and saved agent settings.
enum AppLanguage {
    static var selection: String { UserDefaults.standard.string(forKey: "displayLanguage") ?? "system" }
    static func resolve(_ selection: String, preferred: [String] = Locale.preferredLanguages) -> String {
        if ["ko", "en", "vi"].contains(selection) { return selection }
        for value in preferred {
            let base = value.components(separatedBy: CharacterSet(charactersIn: "-_"))[0]
            if ["ko", "en", "vi"].contains(base) { return base }
        }
        return "en"
    }
    static var code: String { resolve(selection) }
    static var locale: Locale { Locale(identifier: code) }
    static let translations: [String: [String: String]] = {
        #if TESTING
        let url = URL(fileURLWithPath: "Resources/Translations.json")
        #else
        guard let url = Bundle.main.url(forResource: "Translations", withExtension: "json") else { return [:] }
        #endif
        guard let data = try? Data(contentsOf: url),
              let values = try? JSONDecoder().decode([String: [String: String]].self, from: data) else { return [:] }
        return values
    }()
}

func L(_ key: String, _ arguments: String...) -> String {
    let template = AppLanguage.translations[key]?[AppLanguage.code] ?? key
    // Replace placeholders in one pass so user-provided text is never reinterpreted.
    let pattern = try! NSRegularExpression(pattern: #"\{([0-9]+)\}"#)
    var result = template
    for match in pattern.matches(in: template, range: NSRange(template.startIndex..., in: template)).reversed() {
        guard let numberRange = Range(match.range(at: 1), in: template),
              let index = Int(template[numberRange]), index < arguments.count,
              let range = Range(match.range, in: result) else { continue }
        result.replaceSubrange(range, with: arguments[index])
    }
    return result
}

/// Backend messages remain language-neutral at rest; translate only their display text.
func localizedBackend(_ value: String) -> String {
    guard AppLanguage.code != "ko" else { return value }
    if AppLanguage.translations[value] != nil { return L(value) }
    // Dynamic messages have a provider/agent name prefix. Preserve that name verbatim.
    let suffixes = [" CLI를 찾지 못했습니다.", ": 사용 가능한 예비 계정이 없습니다.", ": 예비 계정으로 전환했습니다.",
                    ": 지출 한도 도달", " 크레딧: 무제한"]
    for suffix in suffixes where value.hasSuffix(suffix) {
        return String(value.dropLast(suffix.count)) + L(suffix)
    }
    if let range = value.range(of: " 크레딧: ", options: .backwards) {
        return String(value[..<range.lowerBound]) + L(" 크레딧: ") + value[range.upperBound...]
    }
    return value
}
func localizedQuotaLabel(_ value: String) -> String {
    guard AppLanguage.code != "ko" else { return value }
    var text = value.replacingOccurrences(of: "OAuth 앱", with: "OAuth apps")
    for (unit, en, vi) in [("시간", "hours", "giờ"), ("일", "days", "ngày")] {
        let regex = try! NSRegularExpression(pattern: "([0-9]+(?:\\.[0-9]+)?)" + unit)
        text = regex.stringByReplacingMatches(in: text, range: NSRange(text.startIndex..., in: text),
                                             withTemplate: "$1 " + (AppLanguage.code == "vi" ? vi : en))
    }
    return text.replacingOccurrences(of: "단기", with: L("단기")).replacingOccurrences(of: "장기", with: L("장기"))
}
func displayDate(_ date: Date, timeOnly: Bool = false) -> String {
    let formatter = DateFormatter()
    formatter.locale = AppLanguage.locale
    formatter.dateStyle = timeOnly ? .none : .medium
    formatter.timeStyle = .short
    return formatter.string(from: date)
}
