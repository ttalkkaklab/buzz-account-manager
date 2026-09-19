$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class BuzzShell {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    public static extern int SetCurrentProcessExplicitAppUserModelID(string appId);
    [DllImport("user32.dll")]
    public static extern bool DestroyIcon(IntPtr icon);
}
'@
[void][BuzzShell]::SetCurrentProcessExplicitAppUserModelID('AstraVision.BuzzAccountManager')
[System.Windows.Forms.Application]::EnableVisualStyles()
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$script:state = $null
$script:loading = $false
$script:busy = $false

function Show-Error($message) {
    [void][System.Windows.Forms.MessageBox]::Show([string]$message, 'Buzz Account Manager', 'OK', 'Error')
}
function Invoke-Backend([string]$action, $body = $null) {
    if ($script:busy) { throw '다른 요청을 처리하고 있습니다.' }
    $script:busy = $true
    $form.UseWaitCursor = $true
    $form.Enabled = $false
    try {
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = "$PSScriptRoot\runtime\python.exe"
        $info.Arguments = '-X utf8 "' + "$PSScriptRoot\backend.py" + '" ' + $action
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardInput = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $info.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $info.StandardErrorEncoding = [System.Text.Encoding]::UTF8
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $info
        [void]$process.Start()
        $output = $process.StandardOutput.ReadToEndAsync()
        $errors = $process.StandardError.ReadToEndAsync()
        if ($null -ne $body) {
            $bytes = [System.Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 20 -Compress))
            $process.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
        }
        $process.StandardInput.Close()
        while (-not $process.WaitForExit(50)) { [System.Windows.Forms.Application]::DoEvents() }
        $text = $output.GetAwaiter().GetResult()
        $result = $text | ConvertFrom-Json
        if ($process.ExitCode -ne 0 -or $result.error) {
            if ($result.error) { throw [string]$result.error }
            throw '요청을 처리하지 못했습니다. Buzz와 CLI 설치 상태를 확인하세요.'
        }
        return $result
    } finally {
        if ($process) { $process.Dispose() }
        $script:busy = $false
        $form.UseWaitCursor = $false
        $form.Enabled = $true
    }
}
function Label-At($parent, $text, $x, $y, $width = 130) {
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $text; $label.Location = New-Object System.Drawing.Point($x,$y)
    $label.Size = New-Object System.Drawing.Size($width,25)
    $parent.Controls.Add($label)
}
function Button-At($parent, $text, $x, $y, $width, $callback) {
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $text; $button.Location = New-Object System.Drawing.Point($x,$y)
    $button.Size = New-Object System.Drawing.Size($width,34)
    $button.Add_Click($callback); $parent.Controls.Add($button)
    return $button
}
function Combo-At($parent, $x, $y, $width, $editable = $false) {
    $combo = New-Object System.Windows.Forms.ComboBox
    $combo.Location = New-Object System.Drawing.Point($x,$y)
    $combo.Size = New-Object System.Drawing.Size($width,28)
    if (-not $editable) { $combo.DropDownStyle = 'DropDownList' }
    $parent.Controls.Add($combo)
    return $combo
}
function Fill-Accounts {
    $script:loading = $true
    try {
        $assigned.Items.Clear(); $fallback.Items.Clear()
        foreach ($a in @($script:state.accounts | Where-Object provider -eq $provider.Text)) {
            [void]$assigned.Items.Add($a); [void]$fallback.Items.Add($a)
        }
        if ($assigned.Items.Count) { $assigned.SelectedIndex = 0 }
    } finally { $script:loading = $false }
    Fill-Models
}
function Fill-Models {
    $model.Items.Clear()
    if ($assigned.SelectedItem) {
        foreach ($m in $assigned.SelectedItem.models) { [void]$model.Items.Add($m.id) }
    }
    Fill-Efforts
}
function Fill-Efforts {
    $previous = $effort.Text
    $effort.Items.Clear()
    [void]$effort.Items.Add('')
    $known = @($assigned.SelectedItem.models | Where-Object id -eq $model.Text) | Select-Object -First 1
    if ($provider.Text -eq 'ollama') { $levels = @() }
    elseif ($known) { $levels = @($known.efforts) }
    elseif ($provider.Text -eq 'claude') { $levels = @('low','medium','high','xhigh','max') }
    else { $levels = @('low','medium','high','xhigh','max','ultra') }
    foreach ($level in $levels) { [void]$effort.Items.Add([string]$level) }
    $effort.SelectedIndex = 0
    if ($effort.Items.Contains($previous)) { $effort.SelectedItem = $previous }
}
function Select-Agent {
    if ($script:loading -or -not $agents.SelectedItem) { return }
    $a = $agents.SelectedItem
    $provider.SelectedItem = $a.provider
    Fill-Accounts
    for ($i=0; $i -lt $assigned.Items.Count; $i++) {
        if ($assigned.Items[$i].id -eq $a.account_id) { $assigned.SelectedIndex = $i }
    }
    $model.Text = $a.model; $effort.SelectedItem = [string]$a.effort
    for ($i=0; $i -lt $fallback.Items.Count; $i++) {
        $fallback.SetItemChecked($i, ($a.fallback_ids -contains $fallback.Items[$i].id))
    }
    $automatic.Checked = [bool]$a.auto_fallback
}
function Refresh-State {
    $next = Invoke-Backend 'status'
    $script:loading = $true
    try {
        $script:state = $next
        $agents.Items.Clear(); $accounts.Items.Clear()
        foreach ($a in $next.agents) { [void]$agents.Items.Add($a) }
        foreach ($a in $next.accounts) { [void]$accounts.Items.Add($a) }
        if ($agents.Items.Count) { $agents.SelectedIndex = 0 }
        if ($accounts.Items.Count) { $accounts.SelectedIndex = 0 }
        $status.Text = '에이전트 ' + $agents.Items.Count + '개 · 계정 ' + $accounts.Items.Count + '개'
    } finally { $script:loading = $false }
    Select-Agent
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Buzz Account Manager · Windows Preview'
$form.ShowInTaskbar = $true
$form.ShowIcon = $true
$iconPath = Join-Path $PSScriptRoot 'AppIcon.png'
if (Test-Path $iconPath) {
    $bitmap = New-Object System.Drawing.Bitmap($iconPath)
    $iconHandle = $bitmap.GetHicon()
    try { $form.Icon = [System.Drawing.Icon]::FromHandle($iconHandle).Clone() }
    finally { [void][BuzzShell]::DestroyIcon($iconHandle); $bitmap.Dispose() }
}
$form.ClientSize = New-Object System.Drawing.Size(950,690)
$form.MinimumSize = $form.Size
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object System.Drawing.Font('Malgun Gothic',10)
$tabs = New-Object System.Windows.Forms.TabControl
$tabs.Location = New-Object System.Drawing.Point(16,16)
$tabs.Size = New-Object System.Drawing.Size(918,600)
$tabs.Anchor = 'Top,Bottom,Left,Right'
$form.Controls.Add($tabs)
$agentTab = New-Object System.Windows.Forms.TabPage; $agentTab.Text = '에이전트 설정'
$accountTab = New-Object System.Windows.Forms.TabPage; $accountTab.Text = '계정 관리'
$tabs.TabPages.AddRange(@($agentTab,$accountTab))
$agents = New-Object System.Windows.Forms.ListBox
$agents.Location = New-Object System.Drawing.Point(16,20); $agents.Size = New-Object System.Drawing.Size(250,490)
$agents.DisplayMember = 'name'; $agentTab.Controls.Add($agents)
Label-At $agentTab '서비스' 290 24
$provider = Combo-At $agentTab 425 20 430
$provider.Items.AddRange(@('codex','claude','grok','ollama'))
Label-At $agentTab '사용할 계정' 290 70
$assigned = Combo-At $agentTab 425 66 430; $assigned.DisplayMember = 'name'
Label-At $agentTab '모델 ID' 290 116
$model = Combo-At $agentTab 425 112 430 $true
Label-At $agentTab '추론 강도' 290 162
$effort = Combo-At $agentTab 425 158 430
[void]$effort.Items.Add('')
Label-At $agentTab '예비 계정 (최대 3개)' 290 212 280
$fallback = New-Object System.Windows.Forms.CheckedListBox
$fallback.Location = New-Object System.Drawing.Point(290,244); $fallback.Size = New-Object System.Drawing.Size(565,120)
$fallback.DisplayMember = 'name'; $fallback.CheckOnClick = $true; $agentTab.Controls.Add($fallback)
$automatic = New-Object System.Windows.Forms.CheckBox
$automatic.Text = '잔량이 소진되면 예비 계정으로 자동 전환'; $automatic.Location = New-Object System.Drawing.Point(290,377)
$automatic.Size = New-Object System.Drawing.Size(565,30); $agentTab.Controls.Add($automatic)
Label-At $agentTab '저장 전에 Buzz를 종료하세요. 저장 후 Buzz를 다시 실행하세요.' 290 420 590
Label-At $agentTab '자동 전환은 Buzz 종료를 요청합니다. 진행 중인 응답이 끊길 수 있습니다.' 290 450 600
$save = Button-At $agentTab '설정 저장' 290 493 180 {
    try {
        if (-not $agents.SelectedItem -or -not $assigned.SelectedItem) { throw '에이전트와 계정을 선택하세요.' }
        $ids = @($fallback.CheckedItems | ForEach-Object { $_.id })
        $request = @{ agent_id=$agents.SelectedItem.id; account_id=$assigned.SelectedItem.id; provider=$provider.Text;
                      model=$model.Text; effort=$effort.Text; revision=$script:state.revision;
                      fallback_ids=$ids; auto_fallback=$automatic.Checked; expected_account_id=$agents.SelectedItem.account_id }
        if ($automatic.Checked) { $null = Invoke-Backend 'install-monitor' }
        $result = Invoke-Backend 'apply' $request
        Refresh-State
        [void][System.Windows.Forms.MessageBox]::Show('저장했습니다. Buzz를 다시 실행하세요.', 'Buzz Account Manager')
    } catch { Show-Error $_.Exception.Message }
}
$model.Add_TextChanged({ Fill-Efforts })
$agents.Add_SelectedIndexChanged({ Select-Agent })
$provider.Add_SelectedIndexChanged({ if (-not $script:loading) { Fill-Accounts } })
$assigned.Add_SelectedIndexChanged({ if (-not $script:loading) { Fill-Models } })

$accounts = New-Object System.Windows.Forms.ListBox
$accounts.Location = New-Object System.Drawing.Point(16,20); $accounts.Size = New-Object System.Drawing.Size(320,400)
$accounts.DisplayMember = 'name'; $accountTab.Controls.Add($accounts)
Label-At $accountTab '계정 이름' 360 24
$name = New-Object System.Windows.Forms.TextBox; $name.Location = New-Object System.Drawing.Point(490,20)
$name.Size = New-Object System.Drawing.Size(365,28); $accountTab.Controls.Add($name)
Label-At $accountTab '서비스' 360 70
$newProvider = Combo-At $accountTab 490 66 365
$newProvider.Items.AddRange(@('codex','claude','grok','ollama')); $newProvider.SelectedIndex = 0
Label-At $accountTab 'Ollama 주소' 360 116
$endpoint = New-Object System.Windows.Forms.TextBox; $endpoint.Location = New-Object System.Drawing.Point(490,112)
$endpoint.Size = New-Object System.Drawing.Size(365,28); $endpoint.Text='http://127.0.0.1:11434'; $accountTab.Controls.Add($endpoint)
$add = Button-At $accountTab '계정 추가' 360 158 160 {
    try {
        $created = Invoke-Backend 'create' @{name=$name.Text; provider=$newProvider.Text; endpoint=$endpoint.Text}
        Refresh-State
        Select-AccountById $created.id
    } catch { Show-Error $_.Exception.Message }
}
$saveAccount = Button-At $accountTab '변경 저장' 525 158 160 {
    try {
        if (-not $accounts.SelectedItem) { throw '수정할 계정을 선택하세요.' }
        $identity = $accounts.SelectedItem.id
        $null = Invoke-Backend 'update' @{account_id=$identity; name=$name.Text; endpoint=$endpoint.Text}
        Refresh-State
        Select-AccountById $identity
        $status.Text = '계정 정보를 저장했습니다. 실행 중인 에이전트에는 Buzz 재시작 후 적용됩니다.'
    } catch { Show-Error $_.Exception.Message }
}
$newAccount = Button-At $accountTab '새 계정 입력' 690 158 165 {
    $accounts.ClearSelected()
    $name.Clear(); $name.Enabled=$true
    $newProvider.Enabled=$true; $add.Enabled=$true; $saveAccount.Enabled=$false
    $endpoint.Text='http://127.0.0.1:11434'
    $endpoint.Enabled=($newProvider.Text -eq 'ollama')
    $details.Clear(); $name.Focus()
}
function Select-AccountById($identity) {
    for ($i=0; $i -lt $accounts.Items.Count; $i++) {
        if ($accounts.Items[$i].id -eq $identity) { $accounts.SelectedIndex=$i; break }
    }
}
$newProvider.Add_SelectedIndexChanged({ $endpoint.Enabled=($newProvider.Text -eq 'ollama' -and $name.Enabled) })
$login = Button-At $accountTab '선택 계정 로그인' 360 211 190 {
    try {
        $a=$accounts.SelectedItem
        if (-not $a -or $a.builtin -or $a.provider -eq 'ollama') { throw '추가한 구독 계정을 선택하세요.' }
        # IDs are generated by the backend; never interpolate user-entered names into PowerShell.
        if ($a.id -notmatch '^(codex|claude|grok)-[a-f0-9]+$') { throw '계정 ID를 확인하세요.' }
        $args = '-NoProfile -ExecutionPolicy Bypass -File "' + "$PSScriptRoot\Login.ps1" + '" -AccountId ' + $a.id
        Start-Process -FilePath 'powershell.exe' -ArgumentList $args
    } catch { Show-Error $_.Exception.Message }
}
$delete = Button-At $accountTab '선택 계정 삭제' 565 211 170 {
    try {
        if (-not $accounts.SelectedItem) { return }
        if ([System.Windows.Forms.MessageBox]::Show('선택한 계정을 목록에서 삭제할까요?', '계정 삭제', 'YesNo', 'Question') -ne 'Yes') { return }
        $null = Invoke-Backend 'delete' @{account_id=$accounts.SelectedItem.id}; Refresh-State
    } catch { Show-Error $_.Exception.Message }
}
$usage = Button-At $accountTab '사용량 조회' 360 263 160 {
    try {
        if (-not $accounts.SelectedItem) { return }
        $result = Invoke-Backend 'usage' @{account_id=$accounts.SelectedItem.id}
        $details.Text = $result | ConvertTo-Json -Depth 10
    } catch { Show-Error $_.Exception.Message }
}
$details = New-Object System.Windows.Forms.TextBox
$details.Location = New-Object System.Drawing.Point(360,313); $details.Size = New-Object System.Drawing.Size(495,195)
$details.Multiline=$true; $details.ReadOnly=$true; $details.ScrollBars='Vertical'; $accountTab.Controls.Add($details)
$accounts.Add_SelectedIndexChanged({
    if ($accounts.SelectedItem) {
        $a=$accounts.SelectedItem
        $name.Text=$a.name; $name.Enabled=(-not $a.builtin)
        $newProvider.SelectedItem=$a.provider; $newProvider.Enabled=$false
        $endpoint.Text=[string]$a.endpoint
        $endpoint.Enabled=($a.provider -eq 'ollama' -and -not $a.builtin)
        $saveAccount.Enabled=(-not $a.builtin); $add.Enabled=$false
        $ready = if ($a.ready) { '사용 가능' } else { '로그인 또는 서버 연결 필요' }
        $details.Text = "서비스: $($a.provider)`r`n상태: $ready`r`n계정 경로: $($a.home)"
        if ($a.provider -eq 'ollama') { $details.AppendText("`r`nOllama 주소: $($a.endpoint)") }
        if ($a.builtin) { $details.AppendText("`r`n기본 계정은 수정할 수 없습니다. 새 계정 입력을 누르세요.") }
    }
})
Label-At $accountTab '로그인은 별도 창에서 진행합니다. 완료한 뒤 새로고침하세요.' 16 530 800
$status = New-Object System.Windows.Forms.Label; $status.Location=New-Object System.Drawing.Point(20,639)
$status.Size=New-Object System.Drawing.Size(670,30); $status.Anchor='Bottom,Left'; $form.Controls.Add($status)
$refresh = Button-At $form '새로고침' 772 630 160 { try { Refresh-State } catch { Show-Error $_.Exception.Message } }
$refresh.Anchor='Bottom,Right'
$form.Add_Shown({ try { Refresh-State } catch { $status.Text='Buzz 설치와 에이전트 설정을 확인하세요.'; Show-Error $_.Exception.Message } })
[System.Windows.Forms.Application]::Run($form)
