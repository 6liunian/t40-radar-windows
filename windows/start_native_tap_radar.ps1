$ErrorActionPreference = 'Stop'
$guid = '{8CC242C2-B3ED-4D46-B25E-0761D0EE7690}'
$adapter = Get-NetAdapter | Where-Object { $_.InterfaceGuid -eq $guid }
if (-not $adapter) { throw 'The validated TAP-Windows adapter is missing.' }
$address = Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress '192.168.8.1' -ErrorAction SilentlyContinue
$route = Get-NetRoute -InterfaceIndex $adapter.ifIndex -DestinationPrefix '192.168.8.2/32' -ErrorAction SilentlyContinue
if (-not $address -or -not $route) {
    $setup = Join-Path $PSScriptRoot 'configure_native_tap.ps1'
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $setup + '"'), '-UseHostAddress')
    $process = Start-Process -FilePath powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList $arguments -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw 'TAP configuration failed; inspect native_windows/runtime/configure_radar_tap.log.' }
}
& (Join-Path $PSScriptRoot 'start_native_radar.ps1') -TapGuid $guid
