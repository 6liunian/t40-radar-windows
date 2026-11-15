$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $project 'native_windows\runtime\status.json'
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if ($state.state -ne 'running' -or -not (Get-Process -Id $state.pid -ErrorAction SilentlyContinue)) {
    throw 'Start the native USBWLAN service first.'
}
if (-not ($state.PSObject.Properties.Name -contains 'udp_rx')) {
    throw 'The service must be restarted with UDP bridge support.'
}
$env:RADAR_LOCAL_IP = '127.0.0.1'
$env:RADAR_REMOTE_IP = '127.0.0.2'
if ($state.tap_direct) {
    $env:RADAR_LOCAL_IP = '192.168.8.1'
    $env:RADAR_REMOTE_IP = '192.168.8.2'
}
$env:RADAR_TELEMETRY_PATH = Join-Path $project 'native_windows\runtime\panel.json'
$env:PATH = (Join-Path $project 'windows\pcan-basic-x64\x64') + ';' + $env:PATH
$python = Join-Path $project '.venv\Scripts\pythonw.exe'
$panel = Join-Path $project 'radar_client\radar_control_panel.py'
Start-Process -FilePath $python -ArgumentList @(('"' + $panel + '"')) -WorkingDirectory (Split-Path -Parent $panel) -WindowStyle Hidden
