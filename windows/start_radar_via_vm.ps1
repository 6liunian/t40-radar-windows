$script = Join-Path $PSScriptRoot "start_radar.ps1"
& $script `
    -LocalIp "192.168.1.3" `
    -RadarIp "192.168.1.100" `
    -RadarSshPort 10107 `
    @args
exit $LASTEXITCODE
