param([string]$TapGuid = '')
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$native = Join-Path $project 'native_windows'
$runtime = Join-Path $native 'runtime'
$statePath = Join-Path $runtime 'status.json'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null

function Read-NativeState {
    try { return Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json } catch { return $null }
}

# Reuse a running native transport; never claim USB twice.
$service = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'probe_winusb\.py.*--serve'
} | Select-Object -First 1
if (-not $service) {
    $device = Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -eq 'USB\VID_0CF3&PID_1022\12345678' }
    if (-not $device) { throw 'USBWLAN is not connected.' }
    $binding = Get-PnpDeviceProperty -InstanceId $device.InstanceId -KeyName DEVPKEY_Device_Service
    if ($binding.Data -ne 'WinUSB') { throw 'USBWLAN must be bound to WinUSB.' }
    $python = (Get-Command python -ErrorAction Stop).Source
    & $python -c 'import usb1'
    if ($LASTEXITCODE -ne 0) { throw 'Install libusb1 in this Python environment first.' }
    $stop = Join-Path $runtime 'stop'
    if (Test-Path -LiteralPath $stop) { Remove-Item -LiteralPath $stop }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $log = Join-Path $native "winusb-$stamp.log"
    $errLog = Join-Path $native "winusb-$stamp.err.log"
    $arguments = '-u probe_winusb.py --boot --services --ap --serve'
    if ($TapGuid) {
        if ($TapGuid -notmatch '^\{[0-9a-fA-F-]{36}\}$') { throw 'Invalid TAP GUID' }
        $arguments += " --tap-guid $TapGuid --tap-ip 192.168.8.1 --tap-direct"
    }
    $service = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $native -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $errLog -PassThru
    $serviceId = $service.Id
} else {
    $serviceId = $service.ProcessId
}

$ready = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    $state = Read-NativeState
    if ($state -and $state.pid -eq $serviceId -and $state.state -eq 'running' -and
        ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $state.updated) -lt 15) {
        if ($TapGuid -and -not $state.tap_direct) { throw 'Existing service uses loopback mode. Stop it before switching to TAP.' }
        $ready = $true
        break
    }
    if (-not (Get-Process -Id $serviceId -ErrorAction SilentlyContinue)) {
        throw "Native transport stopped. Inspect native_windows logs. Replug USBWLAN before a fresh boot."
    }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { throw 'Transport has not reported ready; inspect logs before retrying.' }
$panel = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'radar_control_panel\.py'
} | Select-Object -First 1
if ($panel) {
    Write-Host 'The control panel is already running.'
} else {
    & (Join-Path $PSScriptRoot 'start_native_control_panel.ps1')
}
