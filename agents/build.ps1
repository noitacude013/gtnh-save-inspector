# Build the live probe agent (Windows PowerShell).
# Requires a JDK 17+ on PATH (or set %JAVA_HOME%).
# The game JVM locks live-probe-13.jar while it is loaded: close the game before rebuilding,
# or the build will leave a .jar.new file next to it.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$pkg = Join-Path $root 'gtnh_save_inspector\live\agent'
$build = Join-Path $env:TEMP 'gtnh-save-inspector-agent-build'
if (Test-Path $build) { Remove-Item $build -Recurse -Force }
New-Item -ItemType Directory -Force $build | Out-Null
New-Item -ItemType Directory -Force (Join-Path $pkg 'attach') | Out-Null
$javac = if ($env:JAVA_HOME) { Join-Path $env:JAVA_HOME 'bin\javac.exe' } else { 'javac' }
$jarTool = if ($env:JAVA_HOME) { Join-Path $env:JAVA_HOME 'bin\jar.exe' } else { 'jar' }
& $javac --release 8 -encoding UTF-8 -d "$build\agent" "$here\java\LiveProbeAgent13.java"
if ($LASTEXITCODE -ne 0) { throw "javac failed for LiveProbeAgent" }
& $javac --release 11 -encoding UTF-8 -d (Join-Path $pkg 'attach') "$here\java\AttachMain.java"
if ($LASTEXITCODE -ne 0) { throw "javac failed for AttachMain" }
"Agent-Class: LiveProbeAgent13`nCan-Redefine-Classes: false`nCan-Retransform-Classes: false" |
  Out-File -Encoding ascii "$build\manifest.txt"
$tempJar = Join-Path $build 'live-probe-13.jar'
& $jarTool cfm $tempJar "$build\manifest.txt" -C "$build\agent" .
if ($LASTEXITCODE -ne 0) { throw "jar failed" }
$target = Join-Path $pkg 'live-probe-13.jar'
try {
    Copy-Item -Path $tempJar -Destination $target -Force
    Write-Host "built $target"
} catch {
    $pending = "$target.new"
    Copy-Item -Path $tempJar -Destination $pending -Force
    Write-Warning "live-probe-13.jar is locked (game running); wrote $pending - close the game and rename it to live-probe-13.jar"
}
