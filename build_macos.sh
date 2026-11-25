#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Build Atlas for macOS on a Mac or a macOS GitHub Actions runner." >&2
    exit 1
fi

cd "$(dirname -- "$0")"
python="${ATLAS_PYTHON:-.venv/bin/python}"
output="${1:-dist}"
build="${2:-build/macos}"

if ! "$python" -c 'import PyInstaller, tkinter' >/dev/null 2>&1; then
    echo "Install Python 3.12 with Tk and install the project requirements and PyInstaller." >&2
    exit 1
fi

arch="$("$python" -c 'import platform; print(platform.machine())')"
case "$arch" in
    arm64) suffix=arm64 ;;
    x86_64) suffix=x64 ;;
    *) echo "Unsupported Python architecture: $arch" >&2; exit 1 ;;
esac

mkdir -p "$output" "$build"
options=(
    --noconfirm --onedir --windowed --noupx --name Atlas
    --target-arch "$arch" --osx-bundle-identifier com.hyperpants.atlas
    --icon "$PWD/src/api/web/atlas.ico"
    --distpath "$output" --workpath "$build" --specpath "$build"
    --add-data "$PWD/config.yaml:."
    --add-data "$PWD/src/api/web:src/api/web"
    --hidden-import uvicorn.loops.asyncio
    --hidden-import uvicorn.protocols.http.h11_impl
    --hidden-import uvicorn.lifespan.on
)
if [[ -n "${ATLAS_MACOS_SIGN_IDENTITY:-}" ]]; then
    options+=(--codesign-identity "$ATLAS_MACOS_SIGN_IDENTITY")
fi

"$python" -m PyInstaller "${options[@]}" "$PWD/desktop_macos.py"
app="$output/Atlas.app"
codesign --verify --deep --strict "$app"
"$app/Contents/MacOS/Atlas" --check-bundle
zip="$output/Atlas-macOS-$suffix.zip"
ditto -c -k --sequesterRsrc --keepParent "$app" "$zip"
echo "Created $zip"
