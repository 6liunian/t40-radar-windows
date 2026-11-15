# Tests the production native-exit-code handler without changing system drivers.
$ErrorActionPreference = 'Stop'
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'device_setup.ps1'), [ref]$null, [ref]$null)
$definition = $ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Run-Driver'}, $true)
Invoke-Expression $definition.Extent.Text
$script:result = @{reboot=$false}
$script:fakeCode = 0
$script:matched = $true
$script:verifyCalls = 0
function pnputil.exe { $global:LASTEXITCODE=$script:fakeCode; 'mock localized driver output' }
function devcon.exe { $global:LASTEXITCODE=$script:fakeCode; 'mock localized device output' }
function Get-WindowsDriver { param([switch]$Online,[switch]$All)
    $script:verifyCalls++
    [pscustomobject]@{OriginalFileName='staged/usbwlan.inf'; Driver='oem123.inf'}
}
function Get-FileHash { param($LiteralPath,$Algorithm)
    [pscustomobject]@{Hash=$(if ($LiteralPath -eq 'source/usbwlan.inf' -or $script:matched) {'same'} else {'different'})}
}
function Test-Path { param($LiteralPath) $true }
function Assert([bool]$Condition,[string]$Message) { if (-not $Condition) { throw $Message } }
function Expect-Failure([scriptblock]$Block) {
    $thrown=$false
    try { & $Block | Out-Null } catch { $thrown=$true }
    Assert $thrown 'Expected failure was incorrectly accepted'
}
Run-Driver pnputil.exe @('/add-driver','source/usbwlan.inf','/install') | Out-Null
Assert ($script:verifyCalls -eq 0) 'Successful install must not need a store lookup'
$script:fakeCode=259
Run-Driver pnputil.exe @('/add-driver','source/usbwlan.inf','/install') | Out-Null
Assert ($script:verifyCalls -eq 1) '259 must verify the exact staged INF'
Assert (-not $script:result.reboot) '259 does not request a reboot'
$script:matched=$false
Expect-Failure { Run-Driver pnputil.exe @('/add-driver','source/usbwlan.inf','/install') }
Expect-Failure { Run-Driver pnputil.exe @('/delete-driver','source/usbwlan.inf') }
$script:fakeCode=1
Expect-Failure { Run-Driver pnputil.exe @('/add-driver','source/usbwlan.inf','/install') }
Run-Driver devcon.exe @('install','tap.inf','tap0901') | Out-Null
Assert $script:result.reboot 'Devcon exit 1 must request a reboot'
$script:result.reboot=$false
$script:fakeCode=3010
Run-Driver pnputil.exe @('/add-driver','source/usbwlan.inf','/install') | Out-Null
Assert $script:result.reboot 'PnPUtil exit 3010 must request a reboot'
$script:fakeCode=5
Expect-Failure { Run-Driver pnputil.exe @('/add-driver','source/usbwlan.inf','/install') }
'PASS: 8 driver result cases; no hardware, registry, or network changes'
$findDefinition = $ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Find-NewTap'}, $true)
Invoke-Expression $findDefinition.Extent.Text
function Get-NetAdapter { param([switch]$IncludeHidden)
    [pscustomobject]@{PnPDeviceID='ROOT\NET\0001'; InterfaceGuid='changed-old-guid'; InterfaceDescription='TAP-Windows Adapter V9'}
    [pscustomobject]@{PnPDeviceID='ROOT\NET\0003'; InterfaceGuid='new-guid'; InterfaceDescription='TAP-Windows Adapter V9 #2'}
    [pscustomobject]@{PnPDeviceID='OTHER\1'; InterfaceGuid='wifi-guid'; InterfaceDescription='Wi-Fi'}
}
$identified = @(Find-NewTap @('ROOT\NET\0001'))
Assert ($identified.Count -eq 1 -and $identified[0].PnPDeviceID -eq 'ROOT\NET\0003') 'Old TAP GUID changes must not make it look like a newly created device'
'PASS: TAP discovery with changed existing GUID and concurrent unrelated adapter'
