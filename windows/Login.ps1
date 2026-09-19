param([Parameter(Mandatory=$true)][string]$AccountId)
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
& "$PSScriptRoot\runtime\python.exe" -X utf8 "$PSScriptRoot\login_console.py" $AccountId
Write-Host "`n로그인 창을 닫고 Account Manager에서 새로고침하세요."
Read-Host 'Enter 키를 누르면 닫힙니다'
