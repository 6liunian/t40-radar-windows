$ErrorActionPreference = 'Stop'
$log = Join-Path $PSScriptRoot 'restart_usbdk.log'
& sc.exe stop UsbDk 2>&1 | Out-File -LiteralPath $log
if ($LASTEXITCODE -ne 0) { exit 1 }
for ($attempt = 0; $attempt -lt 10; $attempt++) {
    $driver = Get-CimInstance Win32_SystemDriver -Filter "Name='UsbDk'"
    if ($driver.State -eq 'Stopped') { break }
    Start-Sleep -Milliseconds 500
}
if ($driver.State -ne 'Stopped') {
    'Driver did not stop; no further changes made.' | Out-File -LiteralPath $log -Append
    exit 2
}
& sc.exe start UsbDk 2>&1 | Out-File -LiteralPath $log -Append
exit $LASTEXITCODE
