# Build the Windows installer on a Windows PC.
# Needs Python 3.12+ and Inno Setup 6 (winget install JRSoftware.InnoSetup).
# Run from the repo root:  powershell -ExecutionPolicy Bypass -File installer\build.ps1
$ErrorActionPreference = "Stop"
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }
Set-Location (Split-Path $PSScriptRoot -Parent)

$version = (Select-String -Path dmx_suite\__init__.py -Pattern '^__version__\s*=\s*"(.+)"').Matches[0].Groups[1].Value
Write-Host "Building 0.05 DMX Suite $version"

python -m venv .build-venv; Check "venv"
& .build-venv\Scripts\python.exe -m pip install --upgrade pip; Check "pip upgrade"
& .build-venv\Scripts\python.exe -m pip install ".[hw,claude,desktop,dev]" "pyinstaller>=6.10"; Check "pip install"
& .build-venv\Scripts\python.exe -m pytest -q; Check "tests"
& .build-venv\Scripts\pyinstaller.exe installer\dmx-suite.spec --noconfirm --distpath dist --workpath build; Check "PyInstaller"

# smoke test the packaged app against a throwaway show folder
$env:DMX_SUITE_SHOWS = Join-Path $env:TEMP "dmx-suite-smoke\shows"
Remove-Item -Recurse -Force (Split-Path $env:DMX_SUITE_SHOWS) -ErrorAction SilentlyContinue
Copy-Item -Recurse shows $env:DMX_SUITE_SHOWS
& dist\dmx-suite\dmx-suite.exe check
if ($LASTEXITCODE -ne 0) { throw "packaged app failed its show file check" }
Remove-Item Env:DMX_SUITE_SHOWS

# smoke test the desktop app: opens the window on the simulator, checks the page loaded, quits.
# First through the console exe, so any error is printed here, then the windowed exe the shortcuts use.
# app data (logs, settings) in the smoke folder, so desktop.log below is the one these runs write
$env:DMX_SUITE_DATA = Join-Path $env:TEMP "dmx-suite-smoke"
& dist\dmx-suite\dmx-suite.exe --shows (Join-Path $env:TEMP "dmx-suite-smoke\shows") app --sim --fresh --port 8598 --smoke-test 10
Check "desktop app smoke test (console)"
$smokeShows = Join-Path $env:TEMP "dmx-suite-smoke\shows"
$p = Start-Process -FilePath "dist\dmx-suite\0.05 DMX Suite.exe" -PassThru -Wait `
    -ArgumentList "--shows", "`"$smokeShows`"", "app", "--sim", "--fresh", "--port", "8599", "--smoke-test", "10"
Get-Content (Join-Path $env:TEMP "dmx-suite-smoke\logs\desktop.log") -ErrorAction SilentlyContinue
if ($p.ExitCode -ne 0) { throw "desktop app smoke test failed (exit $($p.ExitCode))" }
Remove-Item Env:DMX_SUITE_DATA

# and on a .dms show file (one file for the whole show)
$smokeDms = Join-Path $env:TEMP "dmx-suite-smoke\smoke.dms"
& dist\dmx-suite\dmx-suite.exe pack shows $smokeDms; Check "pack a .dms"
& dist\dmx-suite\dmx-suite.exe --shows $smokeDms check; Check ".dms show file check"
& dist\dmx-suite\dmx-suite.exe --shows $smokeDms app --sim --fresh --port 8597 --smoke-test 10
Check "desktop app smoke test (.dms)"

$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
& $iscc "/DAppVersion=$version" installer\dmx-suite.iss; Check "Inno Setup"
Write-Host "Installer: dist\0.05-DMX-Suite-Setup-$version.exe"
