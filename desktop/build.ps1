param([string]$Nsis, [string]$Python)
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
if (-not $Python) { $Python = Join-Path $project '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $Python)) { throw 'Provide -Python pointing to a Python 3.12 x64 build environment; install requirements-build.txt first.' }
if (-not $Nsis) { $Nsis = (Get-Command makensis.exe -ErrorAction Stop).Source }
$release = Join-Path $project 'release'
New-Item -ItemType Directory -Force $release | Out-Null
& $Python -m PyInstaller --noconfirm --distpath (Join-Path $project 'dist') --workpath (Join-Path $project 'build') (Join-Path $PSScriptRoot 'T40Radar.spec')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
& $Nsis /INPUTCHARSET UTF8 /V2 (Join-Path $PSScriptRoot 'installer.nsi')
if ($LASTEXITCODE -ne 0) { throw 'NSIS failed' }
$installer = Join-Path $release 'T40Radar-Setup-0.5.2-win64.exe'
$hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(($installer + '.sha256'), ($hash + '  ' + [IO.Path]::GetFileName($installer) + "`r`n"), [Text.Encoding]::ASCII)
Get-Item -LiteralPath $installer | Select-Object FullName,Length
