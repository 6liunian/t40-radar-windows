$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project ".venv\Scripts\python.exe"
$pythonw = Join-Path $project ".venv\Scripts\pythonw.exe"
$preflight = Join-Path $PSScriptRoot "preflight.py"
$panel = Join-Path $project "radar_client\radar_control_panel.py"
$pcanRuntime = Join-Path $PSScriptRoot "pcan-basic-x64\x64"

if (-not (Test-Path $python)) {
    throw "Python environment is missing: $python"
}
if (Test-Path $pcanRuntime) {
    $env:PATH = "$pcanRuntime;$env:PATH"
}

Write-Host "Checking radar and PCAN..." -ForegroundColor Cyan
& $python $preflight `
    --can-channel PCAN_USBBUS1 `
    --local-ip 192.168.1.3 `
    --radar-ip 192.168.1.100 `
    --radar-ssh-port 10107
if ($LASTEXITCODE -ne 0) {
    throw "Preflight failed. Keep PCAN on Windows and USBWLAN on the Ubuntu VM."
}

Start-Process -FilePath $pythonw -ArgumentList @($panel) -WorkingDirectory (Split-Path -Parent $panel)
