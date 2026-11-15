param(
    [string]$CanChannel = "PCAN_USBBUS1",
    [string]$LocalIp = "192.168.8.1",
    [string]$RadarIp = "192.168.8.2",
    [int]$RadarSshPort = 107,
    [switch]$NoMotorStart,
    [switch]$NoPlot
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project ".venv\Scripts\python.exe"
$preflight = Join-Path $PSScriptRoot "preflight.py"
$client = Join-Path $project "radar_client\radar_min_client.py"
$capture = Join-Path $project "captures"
$pcanRuntime = Join-Path $PSScriptRoot "pcan-basic-x64\x64"

if (-not (Test-Path $python)) {
    throw "Python environment is missing: $python"
}

if (Test-Path $pcanRuntime) {
    $env:PATH = "$pcanRuntime;$env:PATH"
}

Write-Host "Checking Windows radar connections..." -ForegroundColor Cyan
& $python $preflight --can-channel $CanChannel --local-ip $LocalIp --radar-ip $RadarIp --radar-ssh-port $RadarSshPort
if ($LASTEXITCODE -ne 0) {
    throw "Preflight failed. Fix the failed item(s) above, then run this script again."
}

$clientArgs = @(
    $client,
    "--local-ip", $LocalIp,
    "--radar-ip", $RadarIp,
    "--can-bridge", $CanChannel,
    "--capture-dir", $capture
)
if (-not $NoMotorStart) { $clientArgs += "--send-motor-start" }
if (-not $NoPlot) { $clientArgs += "--plot" }

Write-Host "Starting radar. Press Ctrl+C for a controlled stop." -ForegroundColor Green
& $python @clientArgs

