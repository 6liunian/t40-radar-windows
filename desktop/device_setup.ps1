param(
    [ValidateSet('Install','Check','Remove')] [string]$Mode = 'Check',
    [string]$ResultPath,
    [string]$AppPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'T40Radar.exe')
)
$ErrorActionPreference = 'Stop'
$stateDir = Join-Path $env:ProgramData 'T40Radar'
$statePath = Join-Path $stateDir 'adapter.json'
$pendingPath = Join-Path $stateDir 'adapter-pending.json'
$driverRoot = Join-Path $PSScriptRoot 'drivers'
$result = @{ok=$false; message=''; reboot=$false}

function Run-Driver([string]$Exe, [string[]]$Arguments) {
    $output = & $Exe @Arguments 2>&1 | Out-String
    $code = $LASTEXITCODE
    Write-Output $output
    $allowed = @(0,3010)
    if ([IO.Path]::GetFileName($Exe) -eq 'devcon.exe') { $allowed += 1 }
    # PnPUtil can return ERROR_NO_MORE_ITEMS when the identical package is
    # already staged and the attached device already has the newest driver.
    # Validate the staged INF instead of interpreting localized output text.
    if ($code -eq 259 -and [IO.Path]::GetFileName($Exe) -eq 'pnputil.exe' -and $Arguments[0] -eq '/add-driver') {
        $source = $Arguments[1]
        $digest = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
        $staged = @(Get-WindowsDriver -Online -All | Where-Object {
            [IO.Path]::GetFileName($_.OriginalFileName) -eq [IO.Path]::GetFileName($source)
        } | Where-Object {
            (Test-Path -LiteralPath $_.OriginalFileName) -and
            (Get-FileHash -LiteralPath $_.OriginalFileName -Algorithm SHA256).Hash -eq $digest
        })
        if ($staged.Count) {
            Write-Output ('Verified identical driver already staged: ' + ($staged.Driver -join ', '))
            $allowed += 259
        }
    }
    if ($code -notin $allowed) { throw "Driver command failed ($code): $output" }
    if ($code -in @(1,3010)) { $script:result.reboot = $true }
}
function Saved-Adapter {
    if (-not (Test-Path -LiteralPath $statePath)) { return $null }
    $saved = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    return Get-NetAdapter -IncludeHidden | Where-Object { $_.InterfaceGuid -eq $saved.guid -and $_.PnPDeviceID -eq $saved.instance }
}
function Find-NewTap([string[]]$Before) {
    return @(Get-NetAdapter -IncludeHidden | Where-Object {
        $_.PnPDeviceID -notin $Before -and $_.InterfaceDescription -like 'TAP-Windows Adapter V9*'
    })
}
function Usb-Status {
    $usb = @(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB\VID_0CF3&PID_1022\*' })
    $can = @(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB\VID_0C72&PID_000C\*' })
    $script:result.usb_count = $usb.Count
    $script:result.can_count = $can.Count
    $script:result.usb_service = ''
    $script:result.can_ok = ($can.Count -eq 1 -and $can[0].Status -eq 'OK')
    if ($usb.Count -eq 1) {
        $script:result.usb_service = (Get-PnpDeviceProperty -InstanceId $usb[0].InstanceId -KeyName DEVPKEY_Device_Service).Data
        $script:result.usb_ok = ($usb[0].Status -eq 'OK' -and $script:result.usb_service -eq 'WinUSB')
    }
}

try {
    if ($Mode -ne 'Check') {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
            throw 'Administrator permission is required to install or remove drivers.'
        }
        New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
        Start-Transcript -LiteralPath (Join-Path $stateDir 'device-setup.log') -Append | Out-Null
    }
    if ($Mode -eq 'Remove') {
        Get-NetFirewallRule -Name 'T40Radar-UDP-In' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        $adapter = Saved-Adapter
        if ($adapter) {
            # Remove only the instance created by this application, never all TAP adapters.
            Run-Driver (Join-Path $driverRoot 'tap\devcon.exe') @('remove', ('@' + $adapter.PnPDeviceID))
        }
        if (Test-Path -LiteralPath $statePath) { Remove-Item -LiteralPath $statePath }
        # Leave shared signed USB drivers and the catalog certificate in place: other apps may use them.
        $result.ok = $true
    } else {
        if ($Mode -eq 'Install') {
            $certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new((Join-Path $driverRoot 'winusb\device-catalog.cer'))
            if ($certificate.Thumbprint -ne '84F6FCAF409DD9D3B9AE10128705DC70BA8E0C97') { throw 'Unexpected USBWLAN catalog certificate' }
            foreach ($store in @('Root','TrustedPublisher')) {
                Import-Certificate -FilePath (Join-Path $driverRoot 'winusb\device-catalog.cer') -CertStoreLocation "Cert:\LocalMachine\$store" | Out-Null
            }
            Run-Driver "$env:windir\System32\pnputil.exe" @('/add-driver', (Join-Path $driverRoot 'winusb\usbwlan.inf'), '/install')
            Run-Driver "$env:windir\System32\pnputil.exe" @('/add-driver', (Join-Path $driverRoot 'pcan\pcan_usb.inf'), '/install')
            $adapter = Saved-Adapter
            if (-not $adapter) {
                # Driver updates can change an existing adapter's InterfaceGuid.
                # PnP instance IDs stay tied to the actual device node.
                if (Test-Path -LiteralPath $pendingPath) {
                    $pending = Get-Content -LiteralPath $pendingPath -Raw | ConvertFrom-Json
                    $before = @($pending.before)
                } else {
                    $before = @(Get-PnpDevice -Class Net | ForEach-Object InstanceId)
                    @{before=$before} | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $pendingPath -Encoding UTF8
                    Run-Driver (Join-Path $driverRoot 'tap\devcon.exe') @('install', (Join-Path $driverRoot 'tap\OemVista.inf'), 'tap0901')
                }
                for ($attempt=0; $attempt -lt 15; $attempt++) {
                    $new = @(Find-NewTap $before)
                    if ($new.Count -eq 1) { break }
                    Start-Sleep -Seconds 1
                }
                if ($new.Count -ne 1) { throw 'Unable to identify newly created T40 TAP adapter; inspect device-setup.log.' }
                $adapter = $new[0]
                @{guid=$adapter.InterfaceGuid.ToString(); instance=$adapter.PnPDeviceID} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
                Remove-Item -LiteralPath $pendingPath -ErrorAction SilentlyContinue
                $adapter | Rename-NetAdapter -NewName 'T40 Radar'
                $adapter = Saved-Adapter
            }
            $conflict = @(Get-NetIPAddress -AddressFamily IPv4 -IPAddress '192.168.8.1' -ErrorAction SilentlyContinue | Where-Object InterfaceIndex -ne $adapter.ifIndex)
            if ($conflict.Count) { throw ('192.168.8.1 belongs to another adapter: ' + ($conflict.InterfaceAlias -join ', ') + '. No changes made to that adapter.') }
            if (-not (Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress '192.168.8.1' -ErrorAction SilentlyContinue)) {
                Set-NetIPInterface -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -Dhcp Disabled
                New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress '192.168.8.1' -PrefixLength 32 | Out-Null
            }
            if (-not (Get-NetRoute -InterfaceIndex $adapter.ifIndex -DestinationPrefix '192.168.8.2/32' -ErrorAction SilentlyContinue)) {
                New-NetRoute -InterfaceIndex $adapter.ifIndex -DestinationPrefix '192.168.8.2/32' -NextHop '0.0.0.0' -RouteMetric 5 | Out-Null
            }
            Get-NetFirewallRule -Name 'T40Radar-UDP-In' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
            New-NetFirewallRule -Name 'T40Radar-UDP-In' -DisplayName 'T40 Radar point cloud' -Direction Inbound -Action Allow -Program $AppPath -Protocol UDP -LocalPort 50007,40204 -LocalAddress '192.168.8.1' -RemoteAddress '192.168.8.2' -InterfaceAlias $adapter.Name -Profile Any | Out-Null
        }
        $adapter = Saved-Adapter
        $result.network_ok = $false
        if ($adapter) {
            $result.guid = '{' + $adapter.InterfaceGuid.ToString().Trim('{}') + '}'
            $result.adapter = $adapter.Name
            $ip = Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress '192.168.8.1' -ErrorAction SilentlyContinue
            $route = Get-NetRoute -InterfaceIndex $adapter.ifIndex -DestinationPrefix '192.168.8.2/32' -ErrorAction SilentlyContinue
            $result.network_ok = [bool]($ip -and $route)
        }
        Usb-Status
        $result.ok = [bool]($result.network_ok -and ($Mode -eq 'Install' -or ($result.usb_ok -and $result.can_ok)))
        if (-not $result.network_ok -and -not $result.message) {
            $result.message = 'The dedicated radar adapter address or route is not ready.'
        }
    }
} catch {
    $result.message = $_.Exception.Message
} finally {
    if ($Mode -ne 'Check') { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null }
    $json = $result | ConvertTo-Json -Depth 5
    if ($ResultPath) { [IO.File]::WriteAllText($ResultPath, $json, [Text.UTF8Encoding]::new($false)) }
    Write-Output $json
}
if (-not $result.ok) { exit 2 }
if ($result.reboot) { exit 3010 }
