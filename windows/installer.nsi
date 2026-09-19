Unicode True
!include "MUI2.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
Name "Buzz Account Manager"
OutFile "../build/Buzz-Account-Manager-1.2.0-preview.2-windows-x64-setup.exe"
InstallDir "$LOCALAPPDATA\Programs\Buzz Account Manager"
InstallDirRegKey HKCU "Software\Buzz Account Manager" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
VIProductVersion "1.2.0.2"
VIAddVersionKey /LANG=1033 "ProductName" "Buzz Account Manager"
VIAddVersionKey /LANG=1033 "FileDescription" "Buzz Account Manager Windows Preview Setup"
VIAddVersionKey /LANG=1033 "FileVersion" "1.2.0-preview.2"
VIAddVersionKey /LANG=1033 "LegalCopyright" "MIT License"
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "../LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\Buzz Account Manager.exe"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Korean"
!insertmacro MUI_LANGUAGE "English"
Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "This build requires 64-bit Windows."
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "This build requires Windows 10 or later."
    Abort
  ${EndIf}
FunctionEnd
Section "Buzz Account Manager" SEC_MAIN
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  File /r "../build/windows-payload/*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\Buzz Account Manager"
  CreateShortcut "$SMPROGRAMS\Buzz Account Manager\Buzz Account Manager.lnk" "$INSTDIR\Buzz Account Manager.exe"
  CreateShortcut "$DESKTOP\Buzz Account Manager.lnk" "$INSTDIR\Buzz Account Manager.exe"
  WriteRegStr HKCU "Software\Buzz Account Manager" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\BuzzAccountManager" "DisplayName" "Buzz Account Manager"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\BuzzAccountManager" "DisplayVersion" "1.2.0-preview.2"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\BuzzAccountManager" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\BuzzAccountManager" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\BuzzAccountManager" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\BuzzAccountManager" "NoRepair" 1
SectionEnd
Section "Uninstall"
  SetShellVarContext current
  ReadEnvStr $0 "USERNAME"
  nsExec::ExecToLog '"$SYSDIR\schtasks.exe" /Delete /TN "Buzz Account Manager Monitor-$0" /F'
  Delete "$DESKTOP\Buzz Account Manager.lnk"
  Delete "$SMPROGRAMS\Buzz Account Manager\Buzz Account Manager.lnk"
  RMDir "$SMPROGRAMS\Buzz Account Manager"
  Delete "$INSTDIR\Buzz Account Manager.exe"
  Delete "$INSTDIR\agent-launcher.exe"
  Delete "$INSTDIR\backend.py"
  Delete "$INSTDIR\windows_support.py"
  Delete "$INSTDIR\App.ps1"
  Delete "$INSTDIR\AppIcon.png"
  Delete "$INSTDIR\Login.ps1"
  Delete "$INSTDIR\login_console.py"
  Delete "$INSTDIR\README-Windows.txt"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\__pycache__"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "Software\Buzz Account Manager"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\BuzzAccountManager"
SectionEnd
