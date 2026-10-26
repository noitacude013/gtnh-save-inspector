# Build the single-file Windows GUI executable.
# Run from the repository root with the project venv:
#   .venv\Scripts\python.exe -m PyInstaller --clean --noconfirm packaging\gtnh-save-inspector.spec
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
if (Test-Path "dist\GTNH-Save-Inspector.exe") { Remove-Item "dist\GTNH-Save-Inspector.exe" -Force }
& ".venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm "packaging\gtnh-save-inspector.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$exe = Resolve-Path "dist\GTNH-Save-Inspector.exe"
Write-Host "built $exe"
Write-Host ("size: {0:N1} MB" -f ((Get-Item $exe).Length / 1MB))
