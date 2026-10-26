#!/usr/bin/env bash
# Build the live probe agent (Linux/macOS). Requires JDK 17+.
# The game JVM locks live-probe-13.jar while it is loaded: close the game before rebuilding.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(dirname "$here")"
pkg="$root/gtnh_save_inspector/live/agent"
build="$(mktemp -d)"
mkdir -p "$pkg/attach"
javac --release 8 -encoding UTF-8 -d "$build/agent" "$here/java/LiveProbeAgent13.java"
javac --release 11 -encoding UTF-8 -d "$pkg/attach" "$here/java/AttachMain.java"
printf 'Agent-Class: LiveProbeAgent13\nCan-Redefine-Classes: false\nCan-Retransform-Classes: false\n' > "$build/manifest.txt"
jar cfm "$build/live-probe-13.jar" "$build/manifest.txt" -C "$build/agent" .
if cp "$build/live-probe-13.jar" "$pkg/live-probe-13.jar" 2>/dev/null; then
    echo "built $pkg/live-probe-13.jar"
else
    cp "$build/live-probe-13.jar" "$pkg/live-probe-13.jar.new"
    echo "warning: live-probe-13.jar is locked (game running); wrote live-probe-13.jar.new" >&2
fi
