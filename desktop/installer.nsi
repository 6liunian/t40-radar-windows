Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "FileFunc.nsh"
!define PRODUCT "T40 雷达控制台"
!define VERSION "0.5.2"
Name "${PRODUCT} ${VERSION}"
OutFile "..\release\T40Radar-Setup-${VERSION}-win64.exe"
InstallDir "$PROGRAMFILES64\T40Radar"
InstallDirRegKey HKLM "Software\T40Radar" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
VIProductVersion "0.5.2.0"
VIAddVersionKey /LANG=2052 "ProductName" "${PRODUCT}"
VIAddVersionKey /LANG=2052 "FileDescription" "T40 Radar offline installer"
VIAddVersionKey /LANG=2052 "FileVersion" "0.5.2"
VIAddVersionKey /LANG=2052 "LegalCopyright" "Includes third-party software; see installed notices."
!define MUI_ABORTWARNING
!define MUI_ICON "assets\T40Radar.ico"
!define MUI_UNICON "assets\T40Radar.ico"
!define MUI_WELCOMEPAGE_TEXT "本安装包包含雷达控制面板、运行环境及离线驱动。无需安装 Python 或使用虚拟机。$\r$\n$\r$\n支持 Windows 10/11 64 位，以及当前型号的 USBWLAN 和 PCAN 兼容 USB-CAN。安装后连接设备，从桌面打开控制台。$\r$\n$\r$\n打开软件不会自动启动电机。"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "assets\安装说明.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TEXT "软件文件已安装。若上一步显示设备配置失败，请在控制台点击“修复设备配置”。$\r$\n$\r$\n请将 USBWLAN 和 USB-CAN 连接到此电脑，再从桌面打开控制台。电机需要手动启动。"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Function .onInit
    ${IfNot} ${IsNativeAMD64}
        MessageBox MB_ICONSTOP "此安装包需要 Windows x64。"
        Abort
    ${EndIf}
    SetRegView 64
    # Do not upgrade files while the application is controlling a device.
    System::Call 'kernel32::OpenMutexW(i 0x100000, i 0, w "Local\T40Radar-Desktop-0.1") p.r0'
    ${If} $0 != 0
        System::Call 'kernel32::CloseHandle(p r0)'
        MessageBox MB_ICONSTOP "请先关闭雷达控制台，然后重新安装。"
        Abort
    ${EndIf}
FunctionEnd

Section "控制台及完整运行环境（必选）" Main
    SectionIn RO
    SetShellVarContext all
    SetOutPath "$INSTDIR"
    File /r "..\dist\T40Radar\*.*"
    WriteRegStr HKLM "Software\T40Radar" "InstallDir" "$INSTDIR"
    WriteUninstaller "$INSTDIR\Uninstall.exe"
    CreateDirectory "$SMPROGRAMS\T40 Radar"
    CreateShortcut "$SMPROGRAMS\T40 Radar\T40 雷达控制台.lnk" "$INSTDIR\T40Radar.exe"
    CreateShortcut "$DESKTOP\T40 雷达控制台.lnk" "$INSTDIR\T40Radar.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\T40Radar" "DisplayName" "${PRODUCT}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\T40Radar" "DisplayVersion" "${VERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\T40Radar" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\T40Radar" "InstallLocation" "$INSTDIR"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\T40Radar" "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\T40Radar" "NoRepair" 1
SectionEnd

Section "离线驱动与专用雷达网卡（推荐）" Drivers
    # Packaging smoke tests can install files without changing attached hardware.
    ${GetParameters} $R0
    ClearErrors
    ${GetOptions} $R0 "/FILES_ONLY" $R1
    ${IfNot} ${Errors}
        Goto drivers_done
    ${EndIf}
    SetOutPath "$INSTDIR"
    CreateDirectory "$APPDATA\T40Radar"
    DetailPrint "正在安装 USBWLAN / PCAN 驱动并配置专用网卡…"
    ${DisableX64FSRedirection}
    ExecWait '$\"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe$\" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $\"$INSTDIR\_internal\assets\device_setup.ps1$\" -Mode Install -AppPath $\"$INSTDIR\T40Radar.exe$\" -ResultPath $\"$APPDATA\T40Radar\install-result.json$\"' $0
    ${EnableX64FSRedirection}
    ${If} $0 == 3010
        SetRebootFlag true
    ${ElseIf} $0 != 0
        DetailPrint "设备配置未完成，记录：C:\ProgramData\T40Radar\device-setup.log"
        MessageBox MB_OK|MB_ICONEXCLAMATION "软件文件已安装，但设备配置未完成。请查看 C:\ProgramData\T40Radar\device-setup.log，或打开控制台点击“修复设备配置”。" /SD IDOK
        SetErrorLevel 2
    ${EndIf}
    drivers_done:
SectionEnd

Function un.onInit
    SetRegView 64
    System::Call 'kernel32::OpenMutexW(i 0x100000, i 0, w "Local\T40Radar-Desktop-0.1") p.r0'
    ${If} $0 != 0
        System::Call 'kernel32::CloseHandle(p r0)'
        MessageBox MB_ICONSTOP "请先关闭雷达控制台。"
        Abort
    ${EndIf}
FunctionEnd

Section "Uninstall"
    SetShellVarContext all
    ${DisableX64FSRedirection}
    ExecWait '$\"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe$\" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $\"$INSTDIR\_internal\assets\device_setup.ps1$\" -Mode Remove' $0
    ${EnableX64FSRedirection}
    ${If} $0 != 0
    ${AndIf} $0 != 3010
        MessageBox MB_OK|MB_ICONEXCLAMATION "专用网卡未能卸载，软件文件暂时保留。请查看 C:\ProgramData\T40Radar\device-setup.log 后重试。" /SD IDOK
        SetErrorLevel 2
        Abort
    ${EndIf}
    Delete "$DESKTOP\T40 雷达控制台.lnk"
    Delete "$SMPROGRAMS\T40 Radar\T40 雷达控制台.lnk"
    RMDir "$SMPROGRAMS\T40 Radar"
    # Only remove files installed by this product. User captures and shared USB drivers remain.
    RMDir /r "$INSTDIR\_internal"
    Delete "$INSTDIR\T40Radar.exe"
    Delete "$INSTDIR\Uninstall.exe"
    RMDir "$INSTDIR"
    DeleteRegKey HKLM "Software\T40Radar"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\T40Radar"
SectionEnd
