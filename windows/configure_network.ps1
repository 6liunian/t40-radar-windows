param(
    [string]$AdapterName = "Ethernet"
)

$ErrorActionPreference = "Stop"
$adapter = Get-NetAdapter -Name $AdapterName -ErrorAction Stop
if ($adapter.Status -eq "Disabled") {
    Enable-NetAdapter -Name $AdapterName -Confirm:$false
}

$wantedAddress = "192.168.8.1"

# Windows Mobile Hotspot can leave this address in PersistentStore on a
# disconnected Wi-Fi Direct adapter. Migrate that stale entry to the real
# adapter, otherwise New-NetIPAddress fails with error 5010.
$conflicts = @(
    Get-NetIPAddress -PolicyStore ActiveStore -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -eq $wantedAddress -and $_.InterfaceIndex -ne $adapter.ifIndex }
    Get-NetIPAddress -PolicyStore PersistentStore -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -eq $wantedAddress -and $_.InterfaceIndex -ne $adapter.ifIndex }
)
foreach ($conflict in $conflicts) {
    Remove-NetIPAddress -InputObject $conflict -Confirm:$false -ErrorAction SilentlyContinue
}

$wanted = Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object IPAddress -eq $wantedAddress

if (-not $wanted) {
    New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress $wantedAddress -PrefixLength 24 | Out-Null
}

Write-Host "Configured $AdapterName as 192.168.8.1/24"
Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 |
    Select-Object InterfaceAlias,IPAddress,PrefixLength

$ruleName = "DJI T40 Radar UDP"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
        -Protocol UDP -LocalPort 40204,50007 -Profile Any | Out-Null
    Write-Host "Added Windows Firewall rule for UDP ports 40204 and 50007"
}

