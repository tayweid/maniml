#!/bin/bash
# Build ManimLive.app and install it, as Knuth's and Plass's app/build.sh do,
# minus the compiler: the app is a script (app/ManimLive), the shape of
# Edit <course>.app. It opens ManimLive in a browser window and starts the
# engine when none is running.
#
#   app/build.sh                               # into /Applications
#   app/build.sh ~/Desktop/ManimLive.app       # anywhere else
#   MANIML_PYTHON=/path/to/python app/build.sh # not your maniml command's
#
# Run it again after changing app/; a change to maniml itself needs nothing,
# since the app runs the maniml you have installed.
set -euo pipefail
if [ -n "${1:-}" ]; then
    case "$1" in
        /*) out="$1" ;;
        *) out="$PWD/$1" ;;
    esac
elif [ -w /Applications ]; then
    out="/Applications/ManimLive.app"
else
    mkdir -p "$HOME/Applications"
    out="$HOME/Applications/ManimLive.app"
fi
# The target is replaced wholesale, so it must be an app bundle.
case "$out" in
    *.app) ;;
    *) echo "build.sh: the target must end in .app (got $out)" >&2; exit 1 ;;
esac
cd "$(dirname "$0")"

# The Python the app runs maniml with: the one behind your `maniml` command
# (for development, the editable install of this checkout).
python="${MANIML_PYTHON:-}"
if [ -z "$python" ] && command -v maniml >/dev/null; then
    python="$(head -1 "$(command -v maniml)" | sed 's/^#![[:space:]]*//')"
fi
has_maniml() { [ -x "$1" ] && "$1" -c "import importlib.util, sys; sys.exit(importlib.util.find_spec('maniml') is None)" 2>/dev/null; }
if ! has_maniml "$python"; then
    python="$(command -v python3 || true)"
fi
if ! has_maniml "$python"; then
    echo "build.sh: no Python with maniml found; set MANIML_PYTHON" >&2
    exit 1
fi

rm -rf "$out"
mkdir -p "$out/Contents/MacOS" "$out/Contents/Resources"
cp ManimLive "$out/Contents/MacOS/ManimLive"
chmod +x "$out/Contents/MacOS/ManimLive"
cp Info.plist "$out/Contents/Info.plist"
printf 'APPL????' > "$out/Contents/PkgInfo"
printf '%s\n' "$python" > "$out/Contents/Resources/python"

# The icon, from the one the page uses.
icon_source="../maniml/web/static/icons/maniml-512.png"
iconset="$(mktemp -d)/AppIcon.iconset"
mkdir -p "$iconset"
for size in 16 32 128 256; do
    sips -z "$size" "$size" "$icon_source" --out "$iconset/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" "$icon_source" --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
cp "$icon_source" "$iconset/icon_512x512.png"
iconutil -c icns "$iconset" -o "$out/Contents/Resources/AppIcon.icns"
rm -rf "$(dirname "$iconset")"

echo "built $out (maniml from $python)"
