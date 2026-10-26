# Build the full-dependency single-file GUI exe:
# - embeds a jlink Java runtime (jdk.attach) so live probing needs no installed JDK
# - WebView2 remains a Windows component (present on Win11; browser fallback otherwise)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))

$jlink = if ($env:JAVA_HOME) { Join-Path $env:JAVA_HOME "bin\jlink.exe" } else { "jlink" }
$javac = if ($env:JAVA_HOME) { Join-Path $env:JAVA_HOME "bin\javac.exe" } else { "javac" }
if (-not (Get-Command $jlink -ErrorAction SilentlyContinue) -and -not (Test-Path $jlink)) {
    throw "jlink not found; install a JDK 11+ or set JAVA_HOME"
}

$runtime = Join-Path (Get-Location) "packaging\java-runtime"
if (Test-Path $runtime) { Remove-Item $runtime -Recurse -Force }
& $jlink --add-modules jdk.attach --output $runtime --strip-debug --no-man-pages --no-header-files --compress=2
if ($LASTEXITCODE -ne 0) { throw "jlink failed" }

$env:PATH = (Split-Path -Parent $jlink) + ";" + $env:PATH
$javaExe = Join-Path $runtime "bin\java.exe"
& $javaExe -version
if ($LASTEXITCODE -ne 0) { throw "bundled Java runtime failed" }

& ".venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm "packaging\gtnh-save-inspector-full.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller full build failed" }
$exe = Resolve-Path "dist\GTNH-Save-Inspector-Full.exe"
Write-Host "built $exe"
Write-Host ("size: {0:N1} MB" -f ((Get-Item $exe).Length / 1MB))
