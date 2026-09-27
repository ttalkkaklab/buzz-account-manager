param([Parameter(Mandatory=$true)][string]$AccountId,
      [ValidateSet('ko','en','vi')][string]$Language='en')
. "$PSScriptRoot\Localization.ps1"
$script:language=$Language
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
& "$PSScriptRoot\runtime\python.exe" -X utf8 "$PSScriptRoot\login_console.py" $AccountId $Language
Write-Host ("`n"+(L '로그인이 끝나면 이 창을 닫으세요. 계정 목록은 자동으로 새로고침됩니다.'))
Read-Host (L 'Enter 키를 누르면 닫힙니다')
