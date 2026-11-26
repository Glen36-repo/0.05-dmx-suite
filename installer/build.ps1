# Build the Windows installer on a Windows PC.
# Needs Python 3.12+ and Inno Setup 6 (winget install JRSoftware.InnoSetup).
# Run from the repo root:  powershell -ExecutionPolicy Bypass -File installer\build.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$version = (Select-String -Path pyproject.toml -Pattern '^version\s*=\s*"(.+)"').Matches[0].Groups[1].Value
Write-Host "Building 0.05 DMX Suite $version"

python -m venv .build-venv
& .build-venv\Scripts\python.exe -m pip install --upgrade pip
& .build-venv\Scripts\python.exe -m pip install ".[hw,claude,dev]" "pyinstaller>=6.10"
& .build-venv\Scripts\python.exe -m pytest -q
& .build-venv\Scripts\pyinstaller.exe installer\dmx-suite.spec --noconfirm --distpath dist --workpath build

# smoke test the packaged app against a throwaway show folder
$env:DMX_SUITE_SHOWS = Join-Path $env:TEMP "dmx-suite-smoke\shows"
Remove-Item -Recurse -Force (Split-Path $env:DMX_SUITE_SHOWS) -ErrorAction SilentlyContinue
Copy-Item -Recurse shows $env:DMX_SUITE_SHOWS
& dist\dmx-suite\dmx-suite.exe check
if ($LASTEXITCODE -ne 0) { throw "packaged app failed its show file check" }
Remove-Item Env:DMX_SUITE_SHOWS

$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
& $iscc "/DAppVersion=$version" installer\dmx-suite.iss
Write-Host "Installer: dist\0.05-DMX-Suite-Setup-$version.exe"
