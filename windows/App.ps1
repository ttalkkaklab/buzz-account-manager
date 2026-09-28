$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class BuzzShell {
 [DllImport("shell32.dll",CharSet=CharSet.Unicode)] public static extern int SetCurrentProcessExplicitAppUserModelID(string id);
 [DllImport("user32.dll")] public static extern bool DestroyIcon(IntPtr icon);
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hwnd,int msg,IntPtr w,IntPtr l);
}
'@
[void][BuzzShell]::SetProcessDPIAware()
[void][BuzzShell]::SetCurrentProcessExplicitAppUserModelID('AstraVision.BuzzAccountManager')
[Windows.Forms.Application]::EnableVisualStyles()
. "$PSScriptRoot\Localization.ps1"
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'
$script:state=$null; $script:busy=$false; $script:loading=$false; $script:saving=$false
$script:section='accounts'; $script:filter='all'; $script:agentId=''; $script:message=''; $script:messageValues=@()
$script:usageCache=@{}; $script:expanded=@{}; $script:logins=@{}; $script:hiddenOpen=$false
$script:editorReady=$false; $script:baseline=$null; $script:pendingAccount=''; $script:pendingAgent=''; $script:columns=$false; $script:connectionLost=$false
$script:scale=1.0
$script:bindings=New-Object System.Collections.Generic.List[object]
$script:selection='system'; $settingsKey='HKCU:\Software\Buzz Account Manager'
if (Test-Path $settingsKey) {
 $saved=(Get-ItemProperty $settingsKey -Name DisplayLanguage -ErrorAction SilentlyContinue).DisplayLanguage
 if ($saved -in @('system','ko','en','vi')) { $script:selection=$saved }
}
function Resolve-Language {
 $script:language=$script:selection
 if ($script:language -eq 'system') { $script:language=[Globalization.CultureInfo]::CurrentUICulture.TwoLetterISOLanguageName }
 if ($script:language -notin @('ko','en','vi')) { $script:language='en' }
}
Resolve-Language
function Bind-Text($control,[string]$key) { $control.Text=L $key; $script:bindings.Add(@{Control=$control;Key=$key}) }
function Set-Message([string]$key,[object[]]$values=@()) { $script:message=$key; $script:messageValues=$values }
function Message-Text { if ($script:messageValues.Count) { return L $script:message $script:messageValues }; return Localize-Backend $script:message }
function Show-Error($message) { [void][Windows.Forms.MessageBox]::Show($form,(Localize-Backend ([string]$message)),(L '설정을 확인해 주세요'),'OK','Error') }
function Invoke-Backend([string]$action,$body=$null) {
 if ($script:busy) { throw (L '다른 요청을 처리하고 있습니다.') }
 $requestForm=[Windows.Forms.Form]::ActiveForm
 if ($null -eq $requestForm) { $requestForm=$form }
 $wasEnabled=$requestForm.Enabled; $wasWaitCursor=$requestForm.UseWaitCursor
 $script:busy=$true; $requestForm.UseWaitCursor=$true; $requestForm.Enabled=$false; $process=$null
 try {
  $info=New-Object Diagnostics.ProcessStartInfo
  $info.FileName="$PSScriptRoot\runtime\python.exe"; $info.Arguments='-X utf8 "'+"$PSScriptRoot\backend.py"+'" '+$action
  $info.UseShellExecute=$false; $info.CreateNoWindow=$true
  $info.RedirectStandardInput=$true; $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true
  $info.StandardOutputEncoding=[Text.Encoding]::UTF8; $info.StandardErrorEncoding=[Text.Encoding]::UTF8
  $process=New-Object Diagnostics.Process; $process.StartInfo=$info; [void]$process.Start()
  $output=$process.StandardOutput.ReadToEndAsync(); $errors=$process.StandardError.ReadToEndAsync()
  if ($null -ne $body) {
   $bytes=[Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 20 -Compress))
   $process.StandardInput.BaseStream.Write($bytes,0,$bytes.Length)
  }
  $process.StandardInput.Close()
  while (-not $process.WaitForExit(50)) { [Windows.Forms.Application]::DoEvents() }
  $result=$output.GetAwaiter().GetResult() | ConvertFrom-Json
  if ($process.ExitCode -ne 0 -or $result.error) {
   if ($result.error) { throw [string]$result.error }; throw (L '설정을 읽지 못했습니다. 다시 시도해 주세요.')
  }
  return $result
 } finally {
  if ($process) { $process.Dispose() }; $script:busy=$false
  if (-not $requestForm.IsDisposed) { $requestForm.UseWaitCursor=$wasWaitCursor; $requestForm.Enabled=$wasEnabled }
 }
}
function Label-At($parent,$text,$x,$y,$width=700,$height=26,$size=10) {
 $c=New-Object Windows.Forms.Label; $c.Text=$text; $c.SetBounds($x,$y,$width,$height)
 $style=if ($size -ge 12) { [Drawing.FontStyle]::Bold } else { [Drawing.FontStyle]::Regular }
 $c.Font=New-Object Drawing.Font('Segoe UI',$size,$style); $parent.Controls.Add($c); return $c
}
# One control ladder for every screen: bar 32 (header and save bar), inline 26
# (inside cards and dialogs), compact 22 (caption-sized actions in a card).
$script:tierHeight=@{bar=32;inline=26;compact=22}
function Button-At($parent,$text,$x,$y,$width,$callback,[string]$tier='inline',[switch]$Primary) {
 $c=New-Object Windows.Forms.Button; $c.Text=$text; $c.SetBounds($x,$y,$width,$script:tierHeight[$tier])
 if ($Primary) {
  $c.FlatStyle='Flat'; $c.BackColor=[Drawing.ColorTranslator]::FromHtml('#30B0C7'); $c.ForeColor=[Drawing.Color]::White
  $c.FlatAppearance.BorderSize=0; $c.UseVisualStyleBackColor=$false
 } else { $c.FlatStyle='System' }
 if ($tier -eq 'compact') { $c.Font=New-Object Drawing.Font('Segoe UI',9) }
 $c.Add_Click($callback); $parent.Controls.Add($c); return $c
}
function Combo-At($parent,$x,$y,$width) {
 $c=New-Object Windows.Forms.ComboBox; $c.DropDownStyle='DropDownList'; $c.SetBounds($x,$y,$width,$script:tierHeight['inline'])
 $parent.Controls.Add($c); return $c
}
function Stack($parent,$width=890) {
 $c=New-Object Windows.Forms.FlowLayoutPanel; $c.FlowDirection='TopDown'; $c.WrapContents=$false
 $c.AutoSize=$true; $c.AutoSizeMode='GrowAndShrink'; $c.Width=$width; $c.Margin=New-Object Windows.Forms.Padding(0)
 $parent.Controls.Add($c); return $c
}
function Card($parent,$height,$width=890) {
 $c=New-Object Windows.Forms.Panel; $c.Size=New-Object Drawing.Size($width,$height)
 $c.BackColor=[Drawing.SystemColors]::ControlLightLight; $c.BorderStyle='FixedSingle'
 $c.Margin=New-Object Windows.Forms.Padding(0,0,0,24); $parent.Controls.Add($c); return $c
}
function Provider-Name($id) { return @{codex='Codex';claude='Claude Code';grok='Grok';ollama='Ollama'}[$id] }
function Provider-Color($id) {
 $hex=@{codex='#26806E';claude='#C26E4F';grok='#546BB3'}[$id]
 if ($hex) { return [Drawing.ColorTranslator]::FromHtml($hex) }; return [Drawing.SystemColors]::Highlight
}
function Badge($parent,$id,$x,$y) {
 $c=Label-At $parent (Provider-Name $id) $x $y 150 29 9
 $c.AutoSize=$true; $c.Padding=New-Object Windows.Forms.Padding(8,3,8,3)
 $c.Font=New-Object Drawing.Font('Segoe UI',9,[Drawing.FontStyle]::Bold)
 $color=Provider-Color $id; $c.ForeColor=$color
 $c.BackColor=[Drawing.Color]::FromArgb([int](229.5+$color.R*.1),[int](229.5+$color.G*.1),[int](229.5+$color.B*.1))
}
function Account-Name($a) { if ($a.builtin) { return L ([string]$a.name) }; return [string]$a.name }
function Is-Server($a) { return ($a.provider -eq 'ollama' -or ($a.provider -eq 'codex' -and $a.endpoint)) }
function Clear-Children($parent) { while ($parent.Controls.Count) { $parent.Controls[0].Dispose() } }
function Refresh-State {
 $script:state=Invoke-Backend 'status'
 if ($script:state.monitor.usages) {
  foreach ($entry in $script:state.monitor.usages.PSObject.Properties) {
   if (-not $script:usageCache[$entry.Name] -or $entry.Value.checked_at -gt $script:usageCache[$entry.Name].checked_at) { $script:usageCache[$entry.Name]=$entry.Value }
  }
 }
 if (-not @($script:state.agents | Where-Object id -eq $script:agentId).Count) {
  $first=@($script:state.agents) | Select-Object -First 1; $script:agentId=if ($first) { $first.id } else { '' }
 }
 Render-Content
}
function Refresh-Usage($identity) {
 try { Set-Message '잔량 조회 중…'; Render-Content; $script:usageCache[$identity]=Invoke-Backend 'usage' @{account_id=$identity}; Set-Message ''; Render-Content }
 catch { Set-Message ''; Show-Error $_.Exception.Message; Render-Content }
}
function Add-Quota($parent,$identity,$width) {
 $box=New-Object Windows.Forms.Panel; $box.Width=$width; $box.BackColor=[Drawing.ColorTranslator]::FromHtml('#F5F5F5')
 $box.Margin=New-Object Windows.Forms.Padding(0,8,0,8); $parent.Controls.Add($box)
 $u=$script:usageCache[$identity]; $y=12
 if (-not $u) { [void](Label-At $box (L '잔량 새로고침을 누르면 조회합니다.') 12 $y ($width-24) 32 9); $y+=36 }
 else {
  $windows=@($u.windows | Where-Object { $_ }); $rows=@($windows | Where-Object is_primary)
  if ($script:expanded[$identity]) { $rows=$windows }
  if ($windows.Count -and -not $rows.Count) { [void](Label-At $box (L '기본 사용 한도 정보가 없습니다.') 12 $y ($width-24)); $y+=30 }
  foreach ($w in $rows) {
   $percent=[Math]::Max(0.0,[Math]::Min(100.0,[double]$w.remaining_percent))
   [void](Label-At $box (Localize-QuotaLabel $w.label) 12 $y ([int]($width*.55)) 26 9)
   $remaining=Label-At $box ((L '%.1f%% 남음').Replace('%.1f',$percent.ToString('F1',[Globalization.CultureInfo]::InvariantCulture)).Replace('%%','%')) ([int]($width*.58)) $y ([int]($width*.38)) 26 9
   if ($percent -lt 20) { $remaining.ForeColor=[Drawing.ColorTranslator]::FromHtml('#C2650E') }
   $bar=New-Object Windows.Forms.ProgressBar; $bar.SetBounds(12,($y+27),($width-24),8); $bar.Value=[int]$percent; $box.Controls.Add($bar)
   if ($percent -lt 20) { [void][BuzzShell]::SendMessage($bar.Handle,0x410,[IntPtr]3,[IntPtr]::Zero) }; $y+=44
   $reset=[DateTimeOffset]::MinValue
   if ($w.resets_at -and [DateTimeOffset]::TryParse([string]$w.resets_at,[ref]$reset)) {
    if ($reset -lt [DateTimeOffset]::Now) { [void](Label-At $box (L '초기화 시각이 지났습니다. 잔량을 새로고침하세요.') 12 $y ($width-24) 38 9); $y+=40 }
    else { [void](Label-At $box (Display-Reset $w.resets_at) 12 $y ($width-24) 26 9); $y+=28 }
   }
  }
  foreach ($note in @($u.notes)) {
   if (-not $note) { continue }; $warning=$note -match '사용을 제한|한도 도달'
   if ($warning -or $script:expanded[$identity]) { $n=Label-At $box (Localize-Backend $note) 12 $y ($width-24) 40 9; if ($warning) { $n.ForeColor=[Drawing.Color]::DarkOrange }; $y+=42 }
  }
  if ($u.message) { [void](Label-At $box (Localize-Backend $u.message) 12 $y ($width-24) 44 9); $y+=46 }
  if ($windows.Count -or @($u.notes).Count) {
   $toggle=New-Object Windows.Forms.CheckBox; $toggle.Appearance='Button'; $toggle.Text=L '자세히 보기'; $toggle.SetBounds(12,$y,180,30)
   $toggle.Checked=[bool]$script:expanded[$identity]; $toggle.Tag=$identity
   $toggle.Add_Click({ $script:expanded[$this.Tag]=$this.Checked; Render-Content }); $box.Controls.Add($toggle); $y+=36
  }
  if ($u.checked_at) { [void](Label-At $box (L '조회 {0}' @((Display-Date $u.checked_at))) 12 $y ($width-24) 26 9); $y+=28 }
 }
 $box.Height=$y+8; return $box.Height
}
function Start-Login($account) {
 if ($account.id -notmatch '^(codex|claude|grok)-[a-f0-9]+$') { throw (L '로그인을 시작하지 못했습니다. 계정과 CLI 설치를 확인하세요.') }
 if ($script:logins.ContainsKey($account.id)) { return }
 $arguments='-NoProfile -ExecutionPolicy Bypass -File "'+"$PSScriptRoot\Login.ps1"+'" -AccountId '+$account.id+' -Language '+$script:language
 # This console is the documented interactive sign-in UI.
 $script:logins[$account.id]=Start-Process powershell.exe -ArgumentList $arguments -PassThru
 Set-Message '로그인 절차를 시작합니다. 브라우저에서 사용할 계정을 확인해 주세요.'; Render-Content
}
function Move-AccountOrder([string[]]$ids,[string]$dragged,[string]$target) {
 # Pure: the dragged account takes the target's slot; everything else keeps its place.
 $list=[System.Collections.Generic.List[string]]::new([string[]]$ids)
 $from=$list.IndexOf($dragged); $to=$list.IndexOf($target)
 if ($from -lt 0 -or $to -lt 0 -or $from -eq $to) { return [string[]]$ids }
 $list.RemoveAt($from); $list.Insert($to,$dragged); return [string[]]$list
}
function Reorder-Account([string]$dragged,[string]$target) {
 if ($script:logins.Count -or $dragged -eq $target) { return }
 $accounts=@($script:state.accounts); $source=@($accounts | Where-Object id -eq $dragged) | Select-Object -First 1; $dest=@($accounts | Where-Object id -eq $target) | Select-Object -First 1
 if (-not $source -or -not $dest -or $source.provider -ne $dest.provider) { return }
 # Only this service's ids travel; the backend refills just the slots they held, so other services keep their places.
 $order=Move-AccountOrder @($accounts | Where-Object provider -eq $source.provider | ForEach-Object { [string]$_.id }) $dragged $target
 try { $r=Invoke-Backend 'reorder' @{account_ids=@($order)}; Set-Message $r.message; Refresh-State } catch { Show-Error $_.Exception.Message }
}
function Enable-AccountDrop($control,[string]$identity) {
 $control.AllowDrop=$true; $control.Tag=$identity
 $control.Add_DragEnter({ param($sender,$e) if ($e.Data.GetDataPresent([string])) { $e.Effect=[Windows.Forms.DragDropEffects]::Move } })
 $control.Add_DragDrop({ param($sender,$e) Reorder-Account ([string]$e.Data.GetData([string])) ([string]$sender.Tag) })
}
function Remove-Account($account) {
 $body=L '{0} 계정을 목록에서 제거합니다. 로그인 파일과 저장된 인증정보는 보관합니다.' @((Account-Name $account))
 if ($account.builtin) { $body+="`r`n"+(L '숨긴 기본 계정에서 언제든 복원할 수 있습니다.') }
 if ([Windows.Forms.MessageBox]::Show($form,$body,(L '계정을 목록에서 삭제할까요?'),'YesNo','Question','Button2') -ne 'Yes') { return }
 try { $r=Invoke-Backend 'delete' @{account_id=$account.id}; Set-Message $r.message; Refresh-State } catch { Show-Error $_.Exception.Message }
}
function Show-AccountDialog($account=$null) {
 $edit=$null -ne $account
 $dialog=New-Object Windows.Forms.Form; $dialog.ClientSize=New-Object Drawing.Size(550,470)
 $dialog.AutoScaleDimensions=New-Object Drawing.SizeF(96,96); $dialog.AutoScaleMode='Dpi'
 $dialog.Font=$form.Font; $dialog.FormBorderStyle='FixedDialog'; $dialog.StartPosition='CenterParent'; $dialog.MaximizeBox=$false; $dialog.MinimizeBox=$false
 $dialog.Text=if ($edit) { L '계정 정보 수정' } else { L '구독 계정 추가' }
 [void](Label-At $dialog $dialog.Text 24 20 500 35 16)
 [void](Label-At $dialog (L '알아보기 쉬운 이름을 붙인 뒤 서비스에 로그인하세요.') 24 60 500 46)
 [void](Label-At $dialog (L '서비스') 24 110 130)
 $service=Combo-At $dialog 168 106 354; $service.Items.AddRange(@('Codex','Claude Code','Grok','Ollama')); $providers=@('codex','claude','grok','ollama')
 $default=if ($edit) { $account.provider } elseif ($script:filter -ne 'all') { $script:filter } else { 'codex' }
 $service.SelectedIndex=[Array]::IndexOf($providers,$default); $service.Enabled=(-not $edit)
 [void](Label-At $dialog (L '계정 이름') 24 151 130)
 $name=New-Object Windows.Forms.TextBox; $name.SetBounds(168,148,354,28); $name.MaxLength=80; $name.AccessibleName=L '계정 이름'; $dialog.Controls.Add($name)
 if ($edit) { $name.Text=$account.name }
 $local=New-Object Windows.Forms.CheckBox; $local.Text=L '로컬 OpenAI 호환 서버'; $local.SetBounds(24,190,500,30); $dialog.Controls.Add($local)
 $local.Checked=($edit -and $account.provider -eq 'codex' -and [bool]$account.endpoint); $local.Enabled=(-not $edit)
 $addressLabel=Label-At $dialog (L '서버 주소') 24 234 140
 $address=New-Object Windows.Forms.TextBox; $address.SetBounds(168,230,354,28); $dialog.Controls.Add($address)
 $address.Text=if ($edit) { [string]$account.endpoint } else { 'http://127.0.0.1:11434' }
 $hint=Label-At $dialog '' 24 270 500 62 9
 [void](Label-At $dialog (L '비밀번호와 토큰은 해당 CLI가 보관합니다. 이 앱에는 직접 입력하지 않습니다.') 24 337 500 60 9)
 $cancel=Button-At $dialog (L '취소') 24 410 120 { $this.FindForm().DialogResult='Cancel' } 'inline'; $cancel.DialogResult='Cancel'; $dialog.CancelButton=$cancel
 $submit=Button-At $dialog '' 312 410 210 {} 'inline' -Primary; $dialog.AcceptButton=$submit
 $update={
  $p=$providers[$service.SelectedIndex]; $server=$p -eq 'ollama' -or ($p -eq 'codex' -and $local.Checked)
  $local.Visible=$p -eq 'codex'; $address.Visible=$server; $addressLabel.Visible=$server; $address.Enabled=(-not $edit -or $p -eq 'ollama')
  $addressLabel.Text=if ($p -eq 'ollama') { L 'Ollama 서버 주소' } else { L '서버 주소' }
  $hint.Text=if ($p -eq 'codex' -and $server) { L 'Responses API와 도구 호출을 지원하는 서버가 필요합니다. 로그인 없이 연결합니다.' } elseif ($p -eq 'ollama') { L '도구 호출을 지원하는 로컬 모델을 사용합니다. 모델을 설치한 뒤 도구 모음의 새로고침을 누르세요.' } else { L '예: 개인 Pro, 업무 계정' }
  $submit.Text=if ($edit) { L '저장' } elseif ($server) { L '서버 추가' } else { L '추가하고 로그인' }
  $submit.Enabled=$name.Text.Trim().Length -gt 0 -and (-not $server -or $address.Text.Trim().Length -gt 0)
 }
 $service.Add_SelectedIndexChanged($update); $local.Add_CheckedChanged($update); $name.Add_TextChanged($update); $address.Add_TextChanged($update)
 $submit.Add_Click({
  try {
   $p=$providers[$service.SelectedIndex]; $body=@{name=$name.Text;provider=$p}
   if ($p -eq 'ollama' -or ($p -eq 'codex' -and $local.Checked)) { $body.endpoint=$address.Text }
   if ($edit) { $body.account_id=$account.id; $created=Invoke-Backend 'update' $body; Set-Message '계정 정보를 저장했습니다.' } else { $created=Invoke-Backend 'create' $body }
   $dialog.Tag=$created; $dialog.DialogResult='OK'
  } catch { Show-Error $_.Exception.Message }
 })
 & $update
 try {
  if ($dialog.ShowDialog($form) -eq 'OK') {
   $created=$dialog.Tag
   if (-not $edit -and $script:section -eq 'agents') { Set-PendingAccount $script:agentId ([string]$created.id) }
   Refresh-State
   if (-not $edit -and -not (Is-Server $created)) { Start-Login $created }
  }
 } finally { $dialog.Dispose() }
}
function Render-Accounts {
 $stack=Stack $accountPage; $stack.Location=New-Object Drawing.Point(32,24)
 $header=New-Object Windows.Forms.Panel; $header.Size=New-Object Drawing.Size(890,132); $stack.Controls.Add($header)
 [void](Label-At $header (L '구독 계정') 0 0 430 42 20)
 [void](Label-At $header (L '서비스마다 여러 계정을 등록하고 에이전트에 연결하세요.') 0 46 540 40)
 [void](Button-At $header (L '잔량 새로고침') 550 4 168 {
  try { foreach ($a in @($script:state.accounts)) { if (-not $script:logins.ContainsKey($a.id)) { $script:usageCache[$a.id]=Invoke-Backend 'usage' @{account_id=$a.id} } }; Render-Content } catch { Show-Error $_.Exception.Message }
 } 'bar')
 [void](Button-At $header (L '계정 추가') 732 4 152 { Show-AccountDialog } 'bar' -Primary)
 [void](Label-At $header (Message-Text) 0 87 880 42 9)
 $filters=New-Object Windows.Forms.FlowLayoutPanel; $filters.Size=New-Object Drawing.Size(890,42); $filters.AccessibleName=L '프로바이더 필터'; $stack.Controls.Add($filters)
 foreach ($id in @('all','codex','claude','grok','ollama')) {
  $count=if ($id -eq 'all') { @($script:state.accounts).Count } else { @($script:state.accounts | Where-Object provider -eq $id).Count }
  $title=if ($id -eq 'all') { L '전체' } elseif ($id -eq 'claude') { 'Claude' } else { Provider-Name $id }
  $r=New-Object Windows.Forms.RadioButton; $r.Appearance='Button'; $r.FlatStyle='System'; $r.Text="$title ($count)"; $r.AutoSize=$true
  $r.MinimumSize=New-Object Drawing.Size(100,28); $r.Margin=New-Object Windows.Forms.Padding(0); $r.Tag=$id; $r.Checked=$script:filter -eq $id
  $r.Add_Click({ $script:filter=$this.Tag; Render-Content }); $filters.Controls.Add($r)
 }
 $visible=@($script:state.accounts | Where-Object { $script:filter -eq 'all' -or $_.provider -eq $script:filter })
 if (-not $visible.Count) { $empty=Card $stack 130; $text=Label-At $empty (L '표시할 계정이 없습니다.') 20 22 850 35; $text.TextAlign='MiddleCenter'; [void](Button-At $empty (L '계정 추가') 345 70 200 { Show-AccountDialog } 'inline') }
 foreach ($p in @('codex','claude','grok','ollama')) {
  $group=@($visible | Where-Object provider -eq $p); if (-not $group.Count) { continue }
  $card=Card $stack 100; Badge $card $p 22 18; $blocks=Stack $card 842; $blocks.Location=New-Object Drawing.Point(22,57); $total=57
  foreach ($a in $group) {
   $block=New-Object Windows.Forms.Panel; $block.Width=842; $block.Margin=New-Object Windows.Forms.Padding(0,0,0,9); $blocks.Controls.Add($block)
   $accountIcon=Label-At $block ([string][char]$(if ($a.builtin) { 0xE7F4 } else { 0xE77B })) 0 0 32 32 16
   $accountIcon.Font=New-Object Drawing.Font('Segoe MDL2 Assets',16)
   $nameLabel=Label-At $block (Account-Name $a) 46 0 439 28 11
   $handle=Label-At $block ([string][char]0xE700) 606 0 32 32 14; $handle.Font=New-Object Drawing.Font('Segoe MDL2 Assets',14)
   $handle.TextAlign='MiddleCenter'; $handle.Cursor=[Windows.Forms.Cursors]::SizeAll; $handle.AccessibleName=L '끌어서 순서 변경'; $handle.Tag=$a.id
   $handle.Add_MouseDown({ param($sender,$e) if ($e.Button -eq 'Left' -and -not $script:logins.Count) { [void]$sender.DoDragDrop([string]$sender.Tag,[Windows.Forms.DragDropEffects]::Move) } })
   foreach ($target in @($block,$accountIcon,$nameLabel,$handle)) { Enable-AccountDrop $target $a.id }
   if (-not $a.builtin) { $edit=Button-At $block (L '계정 정보 수정') 650 0 180 { Show-AccountDialog $this.Tag } 'inline'; $edit.Tag=$a }
   $server=Is-Server $a
   $statusKey=if ($server) { if ($a.ready) { '서버 연결됨' } else { '서버 연결 필요' } } else { if ($a.ready) { '로그인 정보 있음' } else { '로그인 필요' } }
   $stateLabel=Label-At $block (L $statusKey) 0 34 560 26 9; if (-not $a.ready) { $stateLabel.ForeColor=[Drawing.Color]::DarkOrange }; Enable-AccountDrop $stateLabel $a.id
   $path=New-Object Windows.Forms.TextBox; $path.Text=if ($server) { $a.endpoint } else { $a.home }; $path.ReadOnly=$true; $path.BorderStyle='None'; $path.BackColor=$block.BackColor
   $path.Font=New-Object Drawing.Font('Consolas',9); $path.SetBounds(0,64,830,24); $block.Controls.Add($path)
   if ($server -or -not $a.builtin) {
    $key=if ($server) { '연결 확인' } elseif ($a.ready) { '다시 로그인' } else { '로그인' }
    $main=Button-At $block (L $key) 650 34 180 { try { if (Is-Server $this.Tag) { Refresh-State } else { Start-Login $this.Tag } } catch { Show-Error $_.Exception.Message } } 'inline'
    $main.Tag=$a; $main.Enabled=(-not $script:logins.ContainsKey($a.id))
   } else { [void](Label-At $block (L '기본 계정') 650 36 180 26 9) }
   $quota=Stack $block 830; $quota.Location=New-Object Drawing.Point(0,90); $qh=Add-Quota $quota $a.id 830; $y=90+$qh+16
   $refresh=Button-At $block (L '이 계정 잔량 새로고침') 0 $y 360 { Refresh-Usage $this.Tag } 'compact'; $refresh.Tag=$a.id; $refresh.Enabled=(-not $script:logins.ContainsKey($a.id))
   $delete=Button-At $block (L '계정 삭제') 650 $y 180 { Remove-Account $this.Tag } 'compact'; $delete.Tag=$a; $delete.Enabled=(-not $script:logins.ContainsKey($a.id)); $delete.ForeColor=[Drawing.Color]::Firebrick
   $block.Height=$y+43; $total+=$block.Height+9
  }; $card.Height=$total+18
 }
 $hidden=@($script:state.hidden_accounts | Where-Object { $_.builtin -and ($script:filter -eq 'all' -or $_.provider -eq $script:filter) })
 if ($hidden.Count) {
  $panel=Card $stack (48+$(if ($script:hiddenOpen) { 42*$hidden.Count } else { 0 }))
  $toggle=New-Object Windows.Forms.CheckBox; $toggle.Appearance='Button'; $toggle.Text=(L '숨긴 기본 계정')+" ($($hidden.Count))"; $toggle.SetBounds(12,8,500,32)
  $toggle.Checked=$script:hiddenOpen; $toggle.Add_Click({ $script:hiddenOpen=$this.Checked; Render-Content }); $panel.Controls.Add($toggle)
  if ($script:hiddenOpen) {
   $y=48; foreach ($a in $hidden) {
    [void](Label-At $panel ((Provider-Name $a.provider)+' · '+(Account-Name $a)) 22 $y 620 34)
    $restore=Button-At $panel (L '복원') 688 $y 174 { try { $r=Invoke-Backend 'restore' @{account_id=$this.Tag}; Set-Message $r.message; Refresh-State } catch { Show-Error $_.Exception.Message } } 'inline'
    $restore.Tag=$a.id; $restore.Enabled=$script:logins.Count -eq 0; $y+=42
   }
  }
 }
 foreach ($key in @('잔량은 서비스가 제공한 구독 한도의 남은 비율입니다. 정확한 토큰 수로 환산하지 않습니다. 조회 시각 이후의 사용량은 새로고침하면 반영됩니다.','새 계정은 별도 경로에 로그인합니다. 기존 CLI의 기본 계정은 변경하지 않습니다.','별도 계정은 CLI 설정과 세션도 분리됩니다. 로그인 만료·구독 한도·모델 접근 권한은 서비스가 실행 시 확인합니다.')) {
  $note=Label-At $stack (L $key) 0 0 880 48 9; $note.ForeColor=[Drawing.SystemColors]::GrayText
 }
}
function Fill-Fallbacks {
 if ($script:loading) { return }
 $script:loading=$true
 try {
  $selected=@($fallbacks | ForEach-Object { if ($_.SelectedItem) { $_.SelectedItem.id } else { '' } })
  for ($i=0; $i -lt 3; $i++) {
   $combo=$fallbacks[$i]; $combo.Items.Clear(); [void]$combo.Items.Add([pscustomobject]@{id='';name=(L '선택 안 함')})
   foreach ($a in @($script:state.accounts | Where-Object provider -eq $provider.SelectedItem)) {
    if ($a.id -eq $assigned.SelectedItem.id -or ($selected -contains $a.id -and $selected[$i] -ne $a.id)) { continue }
    $title=Account-Name $a; if (-not $a.ready) { $title+=' · '+(L '로그인 필요') }
    [void]$combo.Items.Add([pscustomobject]@{id=$a.id;name=$title})
   }
   $combo.SelectedIndex=0
   for ($j=0; $j -lt $combo.Items.Count; $j++) { if ($combo.Items[$j].id -eq $selected[$i]) { $combo.SelectedIndex=$j } }
  }
 } finally { $script:loading=$false }
}
function Fill-Efforts {
 $previous=$effort.SelectedItem; $effort.Items.Clear(); [void]$effort.Items.Add((L '모델 기본값'))
 $known=@($assigned.SelectedItem.models | Where-Object id -eq $model.Text) | Select-Object -First 1
 $levels=if ($provider.SelectedItem -eq 'ollama' -or (Is-Server $assigned.SelectedItem)) { @() } elseif ($known) { @($known.efforts) } elseif ($provider.SelectedItem -eq 'claude') { @('low','medium','high','xhigh','max') } else { @('low','medium','high','xhigh','max','ultra') }
 foreach ($level in $levels) { [void]$effort.Items.Add([string]$level) }
 $effort.SelectedIndex=0; if ($previous -and $effort.Items.Contains($previous)) { $effort.SelectedItem=$previous }
 Update-Save
}
# A account created from the agent screen stays selected across the re-renders
# that Start-Login and the login-completion timer trigger. Only switching agent,
# saving or discarding drops it.
function Set-PendingAccount([string]$agentId,[string]$accountId) { $script:pendingAgent=$agentId; $script:pendingAccount=$accountId }
function Clear-PendingAccount { $script:pendingAgent=''; $script:pendingAccount='' }
function Resolve-Selection([string]$agentId,[string]$savedAccountId,$accounts) {
 if ($script:pendingAccount -and $script:pendingAgent -eq $agentId -and @($accounts | Where-Object id -eq $script:pendingAccount).Count) { return $script:pendingAccount }
 return $savedAccountId
}
# Saved model, effort, fallbacks and auto-switch belong to the saved service.
# When a new account moves the editor to another service, that service's own
# defaults stand - forcing the old model back would leave, say, a Claude account
# pinned to a gpt-* id in manual-entry mode.
function Resolve-SavedRestore($agent,[string]$targetProvider) {
 if ([string]$agent.provider -ne $targetProvider) { return @{restore=$false;model='';effort='';fallbacks=@();auto=$false} }
 return @{restore=$true;model=([string]$agent.model);effort=([string]$agent.effort);
  fallbacks=@(@($agent.fallback_ids) | Where-Object { $_ });auto=[bool]$agent.auto_fallback}
}
function Agent-Baseline($a) {
 return @{provider=[string]$a.provider;account=[string]$a.account_id;model=([string]$a.model).Trim();effort=[string]$a.effort;
  fallbacks=(@(@($a.fallback_ids) | Where-Object { $_ }) -join ',');auto=[bool]$a.auto_fallback}
}
function Agent-Current {
 $ids=@($fallbacks | ForEach-Object { if ($_.SelectedItem -and $_.SelectedItem.id) { [string]$_.SelectedItem.id } })
 return @{provider=[string]$provider.SelectedItem;account=[string]$assigned.SelectedItem.id;model=$model.Text.Trim();
  effort=$(if ($effort.SelectedIndex -gt 0) { [string]$effort.SelectedItem } else { '' });fallbacks=($ids -join ',');
  auto=($automatic.Checked -and $fallbackCard.Visible)}
}
function Agent-Changed {
 if (-not $script:baseline) { return $false }
 $now=Agent-Current
 foreach ($key in @('provider','account','model','effort','fallbacks','auto')) { if ($now[$key] -ne $script:baseline[$key]) { return $true } }
 return $false
}
# Save bar status line, in the order the spec fixes: progress, unsaved changes,
# result, default. Unsaved beats the result so a stale "saved" line cannot hide it.
function Status-Text {
 if (($script:busy -or $script:saving) -and $script:message) { return Message-Text }
 if ($script:connectionLost) { return L '저장한 계정의 실행 연결이 끊겼습니다. 계정을 확인하고 설정 저장을 누르세요.' }
 if (Agent-Changed) { return L '저장하지 않은 변경이 있습니다. 저장하면 실행 중인 Buzz를 종료합니다.' }
 if ($script:message) { return Message-Text }
 return L '설정은 즉시 저장됩니다. Buzz는 직접 시작하세요.'
}
function Update-Save {
 if (-not $script:editorReady -or $save.IsDisposed) { return }
 $changed=Agent-Changed
 $save.Enabled=($changed -and $assigned.SelectedItem -and $assigned.SelectedItem.ready -and $model.Text.Trim().Length -gt 0 -and -not $script:busy -and -not $script:saving)
 $discard.Visible=($changed -and -not $script:busy -and -not $script:saving)
 $saveMessage.Text=Status-Text; $tooltip.SetToolTip($saveMessage,$saveMessage.Text)
}
function Fill-Models {
 $model.Items.Clear()
 foreach ($m in @($assigned.SelectedItem.models)) { if ($m) { [void]$model.Items.Add([string]$m.id) } }
 if ($model.Items.Count) { $model.SelectedIndex=0 } else { $model.Text='' }
 $manual.Enabled=$provider.SelectedItem -ne 'ollama'
 $manual.Checked=$model.Items.Count -eq 0 -and $manual.Enabled
 $model.DropDownStyle=if ($manual.Checked) { 'DropDown' } else { 'DropDownList' }
 $accountState.Text=if ($assigned.SelectedItem.ready) { L '저장된 로그인 정보가 있습니다.' } else { L '계정 설정에서 먼저 로그인하세요.' }
 if (Is-Server $assigned.SelectedItem) { $accountState.Text=[string]$assigned.SelectedItem.endpoint+' · '+(L '도구 호출을 지원하는 로컬 모델을 사용합니다. 모델을 설치한 뒤 도구 모음의 새로고침을 누르세요.') }
 $modelHint.Text=if ($provider.SelectedItem -eq 'ollama') { if ($model.Items.Count) { L 'Ollama 설치 모델' } else { L '사용할 로컬 모델이 없습니다. Ollama 서버에 도구 호출을 지원하는 모델을 설치하고 새로고침하세요.' } } elseif ($provider.SelectedItem -eq 'claude') { L 'CLI 모델 별칭' } else { L '로컬 모델 캐시' }
 $effortHint.Text=if ($provider.SelectedItem -eq 'ollama') { L 'Ollama는 모델의 기본 추론 설정을 사용합니다. 구독 계정의 사용량은 차감하지 않습니다.' } elseif (Is-Server $assigned.SelectedItem) { L '서버에 설치된 로컬 모델을 선택하세요.' } else { L '높을수록 더 오래 생각하며 구독 사용량이 늘 수 있습니다. 지원 범위는 모델마다 다릅니다.' }
 $fallbackCard.Visible=($provider.SelectedItem -in @('codex','claude') -and -not (Is-Server $assigned.SelectedItem))
 $automatic.Checked=$false; Fill-Fallbacks; Fill-Efforts
}
function Fill-Accounts {
 $script:loading=$true
 try {
  $assigned.Items.Clear()
  foreach ($a in @($script:state.accounts | Where-Object provider -eq $provider.SelectedItem)) {
   $copy=$a.PSObject.Copy(); $copy.name=Account-Name $a; [void]$assigned.Items.Add($copy)
  }
  if ($assigned.Items.Count) { $assigned.SelectedIndex=0 }
  foreach ($combo in $fallbacks) { $combo.Items.Clear() }
 } finally { $script:loading=$false }
 Fill-Models
}
function Save-Agent {
 if (-not $save.Enabled -or $script:saving) { return }
 $script:saving=$true; $form.Enabled=$false
 try {
  $a=@($script:state.agents | Where-Object id -eq $script:agentId)[0]
  $ids=@($fallbacks | ForEach-Object { if ($_.SelectedItem.id) { $_.SelectedItem.id } })
  $request=@{agent_id=$a.id;account_id=$assigned.SelectedItem.id;provider=[string]$provider.SelectedItem;model=$model.Text;
   effort=$(if ($effort.SelectedIndex -gt 0) { [string]$effort.SelectedItem } else { '' });revision=$script:state.revision;
   fallback_ids=$ids;auto_fallback=($automatic.Checked -and $fallbackCard.Visible);expected_account_id=$a.account_id}
  $saveMessage.Text=L '로그인과 모델 설정을 확인하는 중…'
  $null=Invoke-Backend 'validate' $request
  $saveMessage.Text=L 'Buzz를 정상 종료하는 중…'
  $null=Invoke-Backend 'stop-buzz'
  $deadline=[DateTime]::UtcNow.AddSeconds(30)
  do {
   $shutdown=Invoke-Backend 'shutdown-status'
   $running=$shutdown.buzz_running
   if (-not $running -and $shutdown.launcher_count -eq 0) { break }
   $pause=[Diagnostics.Stopwatch]::StartNew()
   while ($pause.ElapsedMilliseconds -lt 200) { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 20 }
  } while ([DateTime]::UtcNow -lt $deadline)
  if ($running) { throw (L 'Buzz를 종료하지 못했습니다. 직접 종료한 뒤 다시 적용하세요.') }
  $saveMessage.Text=L '설정을 백업하고 저장하는 중…'
  if ($request.auto_fallback) { $null=Invoke-Backend 'install-monitor' }
  $null=Invoke-Backend 'apply' $request
  Clear-PendingAccount; Set-Message '{0} 설정을 저장했습니다. Buzz는 직접 시작하세요.' @($a.name); Refresh-State
 } catch { Show-Error $_.Exception.Message }
 finally { $script:saving=$false; $form.Enabled=$true; $form.UseWaitCursor=$false; Update-Save }
}
function Card-At($parent,$x,$y,$width) {
 $c=New-Object Windows.Forms.Panel; $c.SetBounds($x,$y,$width,100)
 $c.BackColor=[Drawing.SystemColors]::ControlLightLight; $c.BorderStyle='FixedSingle'
 $parent.Controls.Add($c); return $c
}
function Wide($control) { $control.Anchor='Top,Left,Right'; return $control }
function Build-Settings($parent,$width) {
 $card=Card-At $parent 32 132 $width; $inner=$width-40; $y=20
 [void](Wide (Label-At $card ('01  '+(L 'AI 서비스')) 20 $y $inner 26 12)); $y+=32
 $script:provider=Wide (Combo-At $card 20 $y $inner); $provider.Items.AddRange(@('codex','claude','grok','ollama'))
 $provider.FormattingEnabled=$true; $provider.Add_Format({ $_.Value=Provider-Name ([string]$_.ListItem) }); $y+=42
 [void](Wide (Label-At $card ('02  '+(L '구독 계정')) 20 $y $inner 26 12)); $y+=32
 $script:assigned=Wide (Combo-At $card 20 $y ($inner-190)); $assigned.DisplayMember='name'
 $add=Button-At $card (L '계정 추가') (20+$inner-170) ($y-2) 170 { Show-AccountDialog } 'inline'; $add.Anchor='Top,Right'; $y+=32
 $script:accountState=Wide (Label-At $card '' 20 $y $inner 40 9); $y+=48
 [void](Wide (Label-At $card ('03  '+(L '모델')) 20 $y $inner 26 12)); $y+=32
 $script:model=Wide (Combo-At $card 20 $y $inner); $y+=32
 $script:manual=New-Object Windows.Forms.CheckBox; $manual.Text=L '모델 ID 직접 입력'; $manual.SetBounds(20,$y,$inner,26)
 $manual.Anchor='Top,Left,Right'; $card.Controls.Add($manual); $y+=30
 $script:modelHint=Wide (Label-At $card '' 20 $y $inner 40 9); $y+=48
 [void](Wide (Label-At $card ('04  '+(L 'Effort')) 20 $y $inner 26 12)); $y+=32
 $script:effort=Wide (Combo-At $card 20 $y $inner); $y+=32
 $script:effortHint=Wide (Label-At $card '' 20 $y $inner 44 9); $y+=48
 $card.Height=$y; return $card
}
function Build-Usage($parent,$width,$a) {
 $card=Card-At $parent 32 132 $width; $inner=$width-40
 [void](Label-At $card (L '현재 구독 계정 잔량') 20 18 ($inner-190) 28 12)
 $current=@($script:state.accounts | Where-Object id -eq $a.account_id) | Select-Object -First 1
 [void](Wide (Label-At $card $(if ($current) { Account-Name $current } else { L '계정 등록 필요' }) 20 50 $inner 26))
 $refresh=Button-At $card (L '잔량 새로고침') (20+$inner-170) 16 170 { Refresh-Usage $this.Tag } 'inline'
 $refresh.Anchor='Top,Right'; $refresh.Tag=$a.account_id; $refresh.Enabled=$null -ne $current
 $quota=Stack $card $inner; $quota.Location=New-Object Drawing.Point(20,82)
 $card.Height=102+(Add-Quota $quota $a.account_id $inner); return $card
}
function Build-Fallbacks($parent,$width) {
 $card=Card-At $parent 32 132 $width; $inner=$width-40; $y=20
 [void](Wide (Label-At $card (L '예비 구독 계정 · 최대 3개') 20 $y $inner 28 11)); $y+=34
 $script:fallbacks=@()
 for ($i=0; $i -lt 3; $i++) {
  [void](Label-At $card (L '예비 {0}' @([string]($i+1))) 20 $y 60 26 9)
  $c=Wide (Combo-At $card 86 $y ($inner-66)); $c.DisplayMember='name'; $script:fallbacks+=,$c
  $c.Add_SelectedIndexChanged({ if (-not $script:loading) { Fill-Fallbacks; Update-Save } }); $y+=32
 }
 $y+=4
 $script:automatic=New-Object Windows.Forms.CheckBox; $automatic.Text=L '한도 소진 시 예비 계정으로 자동 전환'
 $automatic.SetBounds(20,$y,$inner,44); $automatic.Anchor='Top,Left,Right'; $card.Controls.Add($automatic)
 $automatic.Add_CheckedChanged({ Update-Save }); $y+=48
 [void](Wide (Label-At $card (L '5분마다 잔량을 조회하고 위 순서대로 전환합니다. 모델과 effort는 유지합니다. 조회 실패 시에는 전환하지 않습니다.') 20 $y $inner 50 9)); $y+=54
 $warning=Wide (Label-At $card (L '앱을 닫아도 이 컴퓨터에 로그인한 동안 동작합니다. 계정을 전환하면 실행 중인 Buzz를 종료합니다. Buzz는 직접 시작하세요.') 20 $y $inner 58 9)
 $warning.ForeColor=[Drawing.Color]::DarkOrange; $y+=62
 if ($script:state.monitor.checked_at) { [void](Wide (Label-At $card (L '자동 조회: {0}' @((Display-Date $script:state.monitor.checked_at))) 20 $y $inner 26 9)); $y+=30 }
 $events=@($script:state.monitor.last_events | ForEach-Object { Localize-Backend $_ }) -join ' / '
 if ($events) { [void](Wide (Label-At $card $events 20 $y $inner 34 9)); $y+=38 }
 $card.Height=$y; return $card
}
# $unit is the unit the controls currently live in: 1 while the fresh tree is
# still logical, $script:scale once Render-Content has scaled it.
function Place-SaveBar([double]$unit=$script:scale) {
 if (-not $script:editorReady -or $script:save.IsDisposed) { return }
 $width=[int]($script:save.Parent.ClientSize.Width*$unit/$script:scale); $s=$unit
 $script:save.Left=$width-[int](204*$s); $script:discard.Left=$width-[int](396*$s)
 $script:saveMessage.Width=[Math]::Max([int](120*$s),$width-[int](420*$s))
}
# Rebuilding the editor seeds every control from the saved agent again.
function Discard-Changes {
 if (-not $script:editorReady -or $script:busy -or $script:saving) { return }
 Clear-PendingAccount; Render-Content
}
# Detail width, not window width: the rail and the agent list make the two differ.
function Layout-Editor([double]$unit=$script:scale) {
 if (-not $script:editorReady) { return }
 $s=$unit; $pad=[int](32*$s); $gap=[int](24*$s); $top=[int](132*$s)
 $detail=[int]($script:editorPanel.ClientSize.Width*$unit/$script:scale)
 $script:columns=$detail -ge [int](1088*$s)
 $right=[int](360*$s)
 $content=[Math]::Max($right,$detail-[int](84*$s))
 $left=$content
 if ($script:columns) { $left=[Math]::Min(($content-$gap-$right),([int](1240*$s)-2*$pad-$gap-$right)) }
 $script:headerPanel.SetBounds($pad,$gap,$content,[int](96*$s))
 $script:settingsCard.SetBounds($pad,$top,$left,$script:settingsCard.Height)
 if ($script:columns) {
  $x=$pad+$left+$gap
  $script:usageCard.SetBounds($x,$top,$right,$script:usageCard.Height)
  $script:fallbackCard.SetBounds($x,($top+$script:usageCard.Height+$gap),$right,$script:fallbackCard.Height)
 } else {
  $y=$top+$script:settingsCard.Height+$gap
  $script:usageCard.SetBounds($pad,$y,$left,$script:usageCard.Height)
  $script:fallbackCard.SetBounds($pad,($y+$script:usageCard.Height+$gap),$left,$script:fallbackCard.Height)
 }
}
function Render-Agents {
 $script:editorReady=$false
 $listPanel=New-Object Windows.Forms.Panel; $listPanel.Dock='Left'; $listPanel.Width=260; $agentPage.Controls.Add($listPanel)
 [void](Label-At $listPanel (L '에이전트') 16 16 228 30 13)
 [void](Label-At $listPanel (L '이 컴퓨터의 에이전트') 16 48 228 42 9)
 $list=New-Object Windows.Forms.ListView; $list.SetBounds(8,94,244,530); $list.Anchor='Top,Bottom,Left,Right'
 $list.View='Details'; $list.FullRowSelect=$true; $list.HeaderStyle='None'; $list.MultiSelect=$false; $list.HideSelection=$false
 [void]$list.Columns.Add((L '계정 이름'),150); [void]$list.Columns.Add((L '서비스'),90); $listPanel.Controls.Add($list)
 foreach ($a in @($script:state.agents)) {
  $item=New-Object Windows.Forms.ListViewItem([string]$a.name); $item.Tag=$a.id; $item.UseItemStyleForSubItems=$false
  $sub=$item.SubItems.Add((Provider-Name $a.provider)); $sub.ForeColor=Provider-Color $a.provider
  [void]$list.Items.Add($item); if ($a.id -eq $script:agentId) { $item.Selected=$true }
 }
 $editor=New-Object Windows.Forms.Panel; $editor.Dock='Fill'; $agentPage.Controls.Add($editor); $editor.BringToFront()
 $a=@($script:state.agents | Where-Object id -eq $script:agentId) | Select-Object -First 1
 if (-not $a) {
  [void](Label-At $listPanel (L '등록된 에이전트가 없습니다. Buzz에서 에이전트를 만든 뒤 새로고침하세요.') 16 94 225 120)
  [void](Label-At $editor (L '에이전트를 선택하세요') 32 32 550 40 20)
  [void](Label-At $editor (L 'Buzz에 등록된 에이전트가 왼쪽에 표시됩니다.') 32 88 550 60); return
 }
 $list.Add_SelectedIndexChanged({
  if ($this.SelectedItems.Count -and $this.SelectedItems[0].Tag -ne $script:agentId) {
   $script:agentId=$this.SelectedItems[0].Tag; Clear-PendingAccount
   [void]$this.BeginInvoke([Action]{ if (-not $form.IsDisposed) { Render-Content } })
  }
 })
 # Dock the save bar before the scroll area so it keeps the bottom 56px.
 $bar=New-Object Windows.Forms.Panel; $bar.Dock='Bottom'; $bar.Height=56; $bar.BackColor=[Drawing.SystemColors]::Control
 $bar.Add_Paint({
  $pen=New-Object Drawing.Pen([Drawing.SystemColors]::ControlLight)
  try { $_.Graphics.DrawLine($pen,0,0,$this.Width,0) } finally { $pen.Dispose() }
 })
 $editor.Controls.Add($bar)
 $scroll=New-Object Windows.Forms.Panel; $scroll.Dock='Fill'; $scroll.AutoScroll=$true; $editor.Controls.Add($scroll); $scroll.BringToFront()
 $script:editorPanel=$editor
 # Build in logical units; Render-Content scales this fresh tree once, then
 # Layout-Editor keeps working in device units with $script:scale.
 $detail=[int]($editor.ClientSize.Width/$script:scale); $script:columns=$detail -ge 1088
 $content=[Math]::Max(360,$detail-84); $left=$content
 if ($script:columns) { $left=[Math]::Min(($content-24-360),(1240-64-24-360)) }
 $script:headerPanel=New-Object Windows.Forms.Panel; $headerPanel.SetBounds(32,24,$content,96); $scroll.Controls.Add($headerPanel)
 [void](Label-At $headerPanel $a.name 0 0 ($content-200) 34 20)
 Badge $headerPanel $a.provider ($content-160) 6
 [void](Label-At $headerPanel (L '구독 계정과 생각의 깊이를 선택하세요.') 0 36 ($content-200) 26)
 [void](Label-At $headerPanel (L '이름 · Buzz 신원 · 팀은 그대로 유지합니다.') 0 66 ($content-200) 26 9)
 $script:connectionLost=[bool]$a.account_connection_lost
 $script:settingsCard=Build-Settings $scroll $left
 $script:usageCard=Build-Usage $scroll $(if ($script:columns) { 360 } else { $left }) $a
 $script:fallbackCard=Build-Fallbacks $scroll $(if ($script:columns) { 360 } else { $left })
 $script:discard=Button-At $bar (L '변경 취소') 0 12 180 { Discard-Changes } 'bar'
 $script:discard.Anchor='Top,Right'; $script:discard.Visible=$false
 $script:save=Button-At $bar (L '설정 저장') 0 12 180 { Save-Agent } 'bar' -Primary
 $script:save.Anchor='Top,Right'
 $script:saveMessage=Label-At $bar '' 24 16 400 30
 $script:saveMessage.Anchor='Top,Left,Right'; $script:saveMessage.AutoEllipsis=$true
 $bar.Add_Resize({ Place-SaveBar })
 $target=Resolve-Selection $a.id ([string]$a.account_id) $script:state.accounts
 $selected=@($script:state.accounts | Where-Object id -eq $target) | Select-Object -First 1
 $provider.SelectedItem=$(if ($selected) { [string]$selected.provider } else { [string]$a.provider }); Fill-Accounts
 for ($i=0; $i -lt $assigned.Items.Count; $i++) { if ($assigned.Items[$i].id -eq $target) { $assigned.SelectedIndex=$i } }
 $restore=Resolve-SavedRestore $a ([string]$provider.SelectedItem)
 Fill-Models
 if ($restore.restore) {
  if ($model.Items.Contains($restore.model)) { $model.SelectedItem=$restore.model } elseif ($provider.SelectedItem -ne 'ollama') { $manual.Checked=$true; $model.DropDownStyle='DropDown'; $model.Text=$restore.model }
 }
 Fill-Efforts; if ($restore.restore -and $effort.Items.Contains($restore.effort)) { $effort.SelectedItem=$restore.effort }
 $script:loading=$true
 for ($i=0; $i -lt [Math]::Min(3,@($restore.fallbacks).Count); $i++) { for ($j=0; $j -lt $fallbacks[$i].Items.Count; $j++) { if ($fallbacks[$i].Items[$j].id -eq $restore.fallbacks[$i]) { $fallbacks[$i].SelectedIndex=$j } } }
 $script:loading=$false; Fill-Fallbacks; $automatic.Checked=$restore.auto
 $provider.Add_SelectedIndexChanged({ if (-not $script:loading) { Fill-Accounts } })
 $assigned.Add_SelectedIndexChanged({ if (-not $script:loading) { Fill-Models } })
 $model.Add_TextChanged({ Fill-Efforts }); $manual.Add_CheckedChanged({ $model.DropDownStyle=if ($this.Checked) { 'DropDown' } else { 'DropDownList' } })
 $effort.Add_SelectedIndexChanged({ Update-Save })
 $script:baseline=Agent-Baseline $a
 $script:editorReady=$true
 $editor.Add_Resize({ Layout-Editor })
 Layout-Editor 1.0; Place-SaveBar 1.0; Update-Save
}
function Render-General {
 $stack=Stack $generalPage; $stack.Location=New-Object Drawing.Point(32,24); [void](Label-At $stack (L '일반 설정') 0 0 890 60 20)
 $card=Card $stack 130; [void](Label-At $card (L '언어') 24 24 300 32 12)
 $choice=Combo-At $card 24 68 520; $choice.Items.AddRange(@((L '시스템 설정'),'한국어','English','Tiếng Việt'))
 $choice.SelectedIndex=[Array]::IndexOf(@('system','ko','en','vi'),$script:selection)
 $choice.Add_SelectedIndexChanged({
  $script:selection=@('system','ko','en','vi')[$this.SelectedIndex]
  if (-not (Test-Path $settingsKey)) { [void](New-Item $settingsKey -Force) }
  [void](New-ItemProperty $settingsKey -Name DisplayLanguage -Value $script:selection -PropertyType String -Force)
  Apply-Language
 })
 $card=Card $stack 224; [void](Label-At $card (L '로컬 설정') 24 24 820 32 12)
 $paths=@((Join-Path $env:USERPROFILE '.config\buzz-agents\account-manager.json'),(Join-Path $env:APPDATA 'xyz.block.buzz.app\agents\managed-agents.json'))
 for ($i=0; $i -lt 2; $i++) { $text=New-Object Windows.Forms.TextBox; $text.ReadOnly=$true; $text.Text=$paths[$i]; $text.SetBounds(24,(72+$i*34),835,28); $text.Font=New-Object Drawing.Font('Consolas',9); $card.Controls.Add($text) }
 [void](Label-At $card (L '계정 정보는 이 컴퓨터에 저장합니다. 설치 파일에는 사용자 계정이나 인증정보가 없습니다.') 24 150 835 62 9)
 $card=Card $stack 176; [void](Label-At $card (L '정보') 24 20 820 30 12)
 [void](Label-At $card (L 'Buzz 계정 관리') 24 60 820 30)
 [void](Label-At $card (L '버전 {0}' @('1.2.0-preview.2')) 24 95 820 26)
 [void](Label-At $card (L 'Windows 미리보기 — 실기 검증 전') 24 130 820 32 9)
}
function Render-Content {
 $form.SuspendLayout(); $script:editorReady=$false
 $graphics=$form.CreateGraphics()
 try { $script:scale=$graphics.DpiX/96.0 } finally { $graphics.Dispose() }
 try {
  foreach ($p in @($accountPage,$agentPage,$generalPage)) { Clear-Children $p; $p.Visible=$false }
  $page=@{accounts=$accountPage;agents=$agentPage;general=$generalPage}[$script:section]; $page.Visible=$true
  if ($script:section -eq 'general') { Render-General }
  elseif (-not $script:state) { [void](Label-At $page (L 'Buzz 설정을 불러오세요.') 32 32 800 60 20) }
  elseif ($script:section -eq 'accounts') { Render-Accounts } else { Render-Agents }
  # These controls are created after Form's initial Dpi autoscale pass.
  # Scale each fresh tree once; point-sized fonts already use the device DPI.
  if ([Math]::Abs($script:scale-1) -gt 0.01) { foreach ($child in $page.Controls) { $child.Scale((New-Object Drawing.SizeF([single]$script:scale,[single]$script:scale))) } }
  foreach ($button in $railButtons) { $button.BackColor=if ($button.Tag -eq $script:section) { [Drawing.ColorTranslator]::FromHtml('#E2F4F7') } else { [Drawing.SystemColors]::Control }; $button.ForeColor=if ($button.Tag -eq $script:section) { [Drawing.SystemColors]::ControlText } else { [Drawing.SystemColors]::GrayText } }
 } finally { $form.ResumeLayout($true) }
}
function Apply-Language {
 Resolve-Language
 foreach ($binding in $script:bindings) { if (-not $binding.Control.IsDisposed) { $binding.Control.Text=L $binding.Key } }
 $form.Text=L 'Buzz 계정 관리'
 $keys=@('계정 설정','에이전트 설정','일반 설정')
 for ($i=0; $i -lt 3; $i++) { $railButtons[$i].AccessibleName=L $keys[$i]; $tooltip.SetToolTip($railButtons[$i],(L $keys[$i])) }
 Render-Content
}
$form=New-Object Windows.Forms.Form; $form.Text=L 'Buzz 계정 관리'; $form.Font=New-Object Drawing.Font('Segoe UI',10)
$form.AutoScaleDimensions=New-Object Drawing.SizeF(96,96); $form.AutoScaleMode='Dpi'
$form.ClientSize=New-Object Drawing.Size(1180,800); $form.MinimumSize=New-Object Drawing.Size(1080,720); $form.StartPosition='CenterScreen'; $form.KeyPreview=$true
$tooltip=New-Object Windows.Forms.ToolTip
$rail=New-Object Windows.Forms.Panel; $rail.Dock='Left'; $rail.Width=72; $rail.BackColor=[Drawing.SystemColors]::Control
$form.Controls.Add($rail)
if (Test-Path "$PSScriptRoot\AppIcon.png") {
 $bitmap=New-Object Drawing.Bitmap("$PSScriptRoot\AppIcon.png"); $iconHandle=$bitmap.GetHicon()
 try { $form.Icon=[Drawing.Icon]::FromHandle($iconHandle).Clone() } finally { [void][BuzzShell]::DestroyIcon($iconHandle) }
 $picture=New-Object Windows.Forms.PictureBox; $picture.Image=$bitmap; $picture.SizeMode='Zoom'; $picture.SetBounds(20,16,32,32); $rail.Controls.Add($picture)
}
$railButtons=@(); $captions=@('계정','에이전트','일반'); $sections=@('accounts','agents','general'); $glyphs=@(0xE192,0xE716,0xE713)
for ($i=0; $i -lt 3; $i++) {
 $button=Button-At $rail '' 6 (64+62*$i) 60 { $script:section=$this.Tag; Render-Content }; $button.Height=56; $button.Tag=$sections[$i]
 $button.Font=New-Object Drawing.Font('Segoe UI',9); $button.Padding=New-Object Windows.Forms.Padding(0); $button.UseCompatibleTextRendering=$true; $button.FlatStyle='Flat'; $button.FlatAppearance.BorderSize=0
 $button.FlatAppearance.MouseOverBackColor=[Drawing.ColorTranslator]::FromHtml('#F2F2F2'); $button.FlatAppearance.MouseDownBackColor=[Drawing.ColorTranslator]::FromHtml('#E6E6E6')
 $glyph=New-Object Drawing.Bitmap(20,20); $graphics=[Drawing.Graphics]::FromImage($glyph); $font=New-Object Drawing.Font('Segoe MDL2 Assets',16,[Drawing.GraphicsUnit]::Point)
 try { $graphics.DrawString([string][char]$glyphs[$i],$font,[Drawing.Brushes]::Black,-3,-3) } finally { $font.Dispose(); $graphics.Dispose() }
 $button.Image=$glyph; $button.TextImageRelation='ImageAboveText'; Bind-Text $button $captions[$i]; $railButtons+=,$button
 # Button's built-in word wrapping splits short captions despite sufficient width.
 # Keep native button semantics and paint its caption as one unpadded line.
 $button.Add_Paint({
  $top=[int]($this.Height*24.0/56.0)
  $rect=New-Object Drawing.Rectangle(0,$top,$this.Width,($this.Height-$top))
  $brush=New-Object Drawing.SolidBrush($this.BackColor)
  try { $_.Graphics.FillRectangle($brush,$rect) } finally { $brush.Dispose() }
  $flags=[Windows.Forms.TextFormatFlags]::HorizontalCenter -bor [Windows.Forms.TextFormatFlags]::VerticalCenter -bor [Windows.Forms.TextFormatFlags]::SingleLine -bor [Windows.Forms.TextFormatFlags]::NoPadding
  [Windows.Forms.TextRenderer]::DrawText($_.Graphics,$this.Text,$this.Font,$rect,$this.ForeColor,$flags)
 })
}
$hostPanel=New-Object Windows.Forms.Panel; $hostPanel.Dock='Fill'; $form.Controls.Add($hostPanel); $hostPanel.BringToFront()
$toolbar=New-Object Windows.Forms.Panel; $toolbar.Dock='Top'; $toolbar.Height=48; $hostPanel.Controls.Add($toolbar)
$refresh=Button-At $toolbar '' 880 7 180 { try { Refresh-State } catch { Show-Error $_.Exception.Message } } 'bar'; $refresh.Anchor='Top,Right'; Bind-Text $refresh '새로고침'
$content=New-Object Windows.Forms.Panel; $content.Dock='Fill'; $hostPanel.Controls.Add($content); $content.BringToFront()
$accountPage=New-Object Windows.Forms.Panel; $agentPage=New-Object Windows.Forms.Panel; $generalPage=New-Object Windows.Forms.Panel
foreach ($page in @($accountPage,$agentPage,$generalPage)) { $page.Dock='Fill'; $page.AutoScroll=$true; $page.Padding=New-Object Windows.Forms.Padding(32); $content.Controls.Add($page) }
$agentPage.Padding=New-Object Windows.Forms.Padding(0)
$form.Add_KeyDown({
 if ($_.KeyCode -eq 'F5') { $refresh.PerformClick(); $_.Handled=$true }
 if ($_.Control -and $_.KeyCode -eq 'S') {
  if ($script:section -eq 'agents' -and $script:editorReady -and $script:save.Enabled) { $script:save.PerformClick() }
  $_.Handled=$true
 }
 if ($_.Control -and $_.KeyCode -in @('D1','D2','D3')) { $railButtons[[int]$_.KeyCode-[int][Windows.Forms.Keys]::D1].PerformClick(); $_.Handled=$true }
})
$loginTimer=New-Object Windows.Forms.Timer; $loginTimer.Interval=1000
$loginTimer.Add_Tick({
 if ($script:busy -or $script:saving) { return }; $changed=$false
 foreach ($id in @($script:logins.Keys)) { if ($script:logins[$id].HasExited) { $script:logins[$id].Dispose(); $script:logins.Remove($id); $changed=$true } }
 if ($changed) { try { Set-Message '로그인 절차가 끝났습니다. 저장된 인증정보를 확인합니다.'; Refresh-State } catch { Show-Error $_.Exception.Message } }
})
$loginTimer.Start()
$form.Add_Shown({ try { Refresh-State } catch { Render-Content; Show-Error $_.Exception.Message } })
$form.Add_FormClosed({ $loginTimer.Stop(); $loginTimer.Dispose(); $tooltip.Dispose(); foreach ($b in $railButtons) { $b.Image.Dispose() } })
Apply-Language
[Windows.Forms.Application]::Run($form)
