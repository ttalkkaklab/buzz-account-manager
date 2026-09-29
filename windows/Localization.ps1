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
    if ($value.Contains("`n")) { return (($value -split "`n" | ForEach-Object { Localize-Backend $_ }) -join "`n") }
    if ($script:catalog.PSObject.Properties[$value]) { return L $value }
    foreach ($suffix in @(' CLI를 찾지 못했습니다.', ': 사용 가능한 예비 계정이 없습니다.', ': 예비 계정으로 전환했습니다.', ': 지출 한도 도달', ' 크레딧: 무제한')) {
        if ($value.EndsWith($suffix)) { return $value.Substring(0, $value.Length-$suffix.Length) + (L $suffix) }
    }
    $credit = ' 크레딧: '
    $index = $value.LastIndexOf($credit, [StringComparison]::Ordinal)
    if ($index -ge 0) { return $value.Substring(0,$index) + (L $credit) + $value.Substring($index+$credit.Length) }
    foreach ($prefix in @('파일: ', '백업: ', '복원 실패: ', '아직 종료되지 않은 에이전트: ', 'Buzz 실행 파일을 찾지 못했습니다. Windows용 Buzz를 설치하세요: ', 'CLI 실행 파일을 확인할 수 없습니다. Buzz에서 실행 도구를 다시 설치하세요: ')) {
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
function Relative-Reset([DateTimeOffset]$date, [DateTimeOffset]$now = [DateTimeOffset]::Now) {
    $seconds = ($date-$now).TotalSeconds
    if ($seconds -lt 0) { return '' }
    if ($seconds -lt 3600) { return L '{0}분 뒤' @([Math]::Max(1,[Math]::Ceiling($seconds/60))) }
    if ($seconds -lt 172800) { return L '{0}시간 뒤' @([Math]::Max(1,[Math]::Ceiling($seconds/3600))) }
    return L '{0}일 뒤' @([Math]::Max(1,[Math]::Ceiling($seconds/86400)))
}
function Display-Reset([string]$value, [DateTimeOffset]$now = [DateTimeOffset]::Now) {
    $date = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse($value, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$date)) { return L '초기화 {0}' @($value) }
    return L '초기화 {0} · {1}' @((Display-Date $value),(Relative-Reset $date $now))
}
