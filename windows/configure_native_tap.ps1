param([switch]$Restore, [switch]$UseHostAddress)
$ErrorActionPreference = 'Stop'
$guid = '{8CC242C2-B3ED-4D46-B25E-0761D0EE7690}'
$adapter = Get-NetAdapter | Where-Object { $_.InterfaceGuid -eq $guid }
if (-not $adapter -or $adapter.InterfaceDescription -ne 'TAP-Windows Adapter V9') { throw 'Expected TAP adapter missing' }
$index = $adapter.ifIndex
$runtime = Join-Path (Split-Path -Parent $PSScriptRoot) 'native_windows\runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$backup = Join-Path $runtime 'radar_tap_original.json'
$aliasBackup = Join-Path $runtime 'radar_wlan_alias_original.json'
Start-Transcript -LiteralPath (Join-Path $runtime 'configure_radar_tap.log') -Force
try {
    if ($Restore) {
        $statePath = Join-Path $runtime 'status.json'
        if (Test-Path -LiteralPath $statePath) {
            $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            if ($state.state -eq 'running' -and (Get-Process -Id $state.pid -ErrorAction SilentlyContinue)) {
                throw 'Stop the native transport before restoring TAP settings.'
            }
        }
        Remove-NetRoute -InterfaceIndex $index -DestinationPrefix '192.168.8.2/32' -Confirm:$false -ErrorAction SilentlyContinue
        Remove-NetIPAddress -InterfaceIndex $index -IPAddress '192.168.8.3' -Confirm:$false -ErrorAction SilentlyContinue
        Remove-NetIPAddress -InterfaceIndex $index -IPAddress '192.168.8.1' -Confirm:$false -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $aliasBackup) {
            $alias = Get-Content -LiteralPath $aliasBackup -Raw | ConvertFrom-Json
            if (-not (Get-NetIPAddress -InterfaceIndex $alias.InterfaceIndex -IPAddress $alias.IPAddress -ErrorAction SilentlyContinue)) {
                New-NetIPAddress -InterfaceIndex $alias.InterfaceIndex -IPAddress $alias.IPAddress -PrefixLength $alias.PrefixLength -PolicyStore ActiveStore | Out-Null
            }
        }
        if (Test-Path -LiteralPath $backup) {
            $original = Get-Content -LiteralPath $backup -Raw | ConvertFrom-Json
            Set-NetIPInterface -InterfaceIndex $index -AddressFamily IPv4 -Dhcp $original.Dhcp
        }
    } else {
        if (-not (Test-Path -LiteralPath $backup)) {
            if ($adapter.Status -ne 'Disconnected') { throw 'TAP is already in use' }
            Get-NetIPInterface -InterfaceIndex $index -AddressFamily IPv4 |
                Select-Object @{N='Dhcp';E={$_.Dhcp.ToString()}},InterfaceMetric |
                ConvertTo-Json | Set-Content -LiteralPath $backup -Encoding UTF8
        }
        $debugIp = '192.168.8.3'
        if ($UseHostAddress) {
            $debugIp = '192.168.8.1'
            $oldAlias = Get-NetIPAddress -IPAddress $debugIp -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object InterfaceIndex -ne $index
            if ($oldAlias) {
                if ($oldAlias.Count -gt 1 -or $oldAlias.PrefixLength -ne 24 -or $oldAlias.InterfaceAlias -ne 'WLAN') { throw 'Unexpected old host address owner' }
                $oldAlias | Select-Object InterfaceIndex,IPAddress,PrefixLength | ConvertTo-Json | Set-Content -LiteralPath $aliasBackup -Encoding UTF8
                Remove-NetIPAddress -InterfaceIndex $oldAlias.InterfaceIndex -IPAddress $debugIp -Confirm:$false
            }
            Remove-NetIPAddress -InterfaceIndex $index -IPAddress '192.168.8.3' -Confirm:$false -ErrorAction SilentlyContinue
        }
        if (-not (Get-NetIPAddress -InterfaceIndex $index -IPAddress $debugIp -ErrorAction SilentlyContinue)) {
            New-NetIPAddress -InterfaceIndex $index -IPAddress $debugIp -PrefixLength 32 -PolicyStore ActiveStore | Out-Null
        }
        if (-not (Get-NetRoute -InterfaceIndex $index -DestinationPrefix '192.168.8.2/32' -ErrorAction SilentlyContinue)) {
            New-NetRoute -InterfaceIndex $index -DestinationPrefix '192.168.8.2/32' -NextHop '0.0.0.0' -RouteMetric 5 -PolicyStore ActiveStore | Out-Null
        }
    }
    Get-NetIPAddress -InterfaceIndex $index -AddressFamily IPv4 | Format-Table IPAddress,PrefixLength,AddressState
} finally { Stop-Transcript }
