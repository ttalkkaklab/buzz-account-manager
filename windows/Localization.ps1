$script:catalog = Get-Content (Join-Path $PSScriptRoot 'Translations.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$script:language = 'en'
function L([string]$key, [object[]]$values = @()) {
    $template = $key
    $entry = $script:catalog.PSObject.Properties[$key]
    if ($script:language -ne 'ko' -and $entry) {
        $translated = $entry.Value.PSObject.Properties[$script:language]
        if ($translated -and $translated.Value) { $template = [string]$translated.Value }
    }
    # Evaluate placeholders in the original template once; names may contain {0}.
    return [regex]::Replace($template, '\{([0-9]+)\}', {
        param($match)
        $index = [int]$match.Groups[1].Value
        if ($index -lt $values.Count) { return [string]$values[$index] }
        return $match.Value
    })
}
function Localize-Backend([string]$value) {
    if ([string]::IsNullOrEmpty($value)) { return '' }
    if ($script:language -eq 'ko') { return $value }
    if ($script:catalog.PSObject.Properties[$value]) { return L $value }
    foreach ($suffix in @(' CLI를 찾지 못했습니다.', ': 사용 가능한 예비 계정이 없습니다.', ': 예비 계정으로 전환했습니다.', ': 지출 한도 도달', ' 크레딧: 무제한')) {
        if ($value.EndsWith($suffix)) { return $value.Substring(0, $value.Length-$suffix.Length) + (L $suffix) }
    }
    $credit = ' 크레딧: '
    $index = $value.LastIndexOf($credit, [StringComparison]::Ordinal)
    if ($index -ge 0) { return $value.Substring(0,$index) + (L $credit) + $value.Substring($index+$credit.Length) }
    foreach ($prefix in @('Buzz 실행 파일을 찾지 못했습니다. Windows용 Buzz를 설치하세요: ', 'CLI 실행 파일을 확인할 수 없습니다. Buzz에서 실행 도구를 다시 설치하세요: ')) {
        if ($value.StartsWith($prefix)) { return (L $prefix) + $value.Substring($prefix.Length) }
    }
    return $value
}
function Localize-QuotaLabel([string]$value) {
    if ($script:language -eq 'ko') { return $value }
    $hours = if ($script:language -eq 'vi') { 'giờ' } else { 'hours' }
    $days = if ($script:language -eq 'vi') { 'ngày' } else { 'days' }
    $value = [regex]::Replace($value, '([0-9]+(?:\.[0-9]+)?)시간', ('$1 ' + $hours))
    $value = [regex]::Replace($value, '([0-9]+(?:\.[0-9]+)?)일', ('$1 ' + $days))
    return $value.Replace('OAuth 앱','OAuth apps').Replace('단기',(L '단기')).Replace('장기',(L '장기'))
}
function Display-Date([string]$value) {
    $date = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse($value, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$date)) { return $value }
    $culture = @{ko='ko-KR'; en='en-US'; vi='vi-VN'}[$script:language]
    return $date.ToLocalTime().ToString('g', [Globalization.CultureInfo]::GetCultureInfo($culture))
}
