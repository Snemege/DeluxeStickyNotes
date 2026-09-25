#!/bin/sh
# Installs the app menu entry and icons for this user (no Flatpak needed).
# Remove with: ./install-local.sh --remove
set -e
ROOT=$(cd "$(dirname "$0")" && pwd)
DATA=${XDG_DATA_HOME:-$HOME/.local/share}
ID=io.github.Snemege.DeluxeStickyNotes
LEGACY_ID=io.github.vex.StickyNotes      # önceki sürümün kimliği: kısayolu ve ikonları temizlenir

remove_legacy() {
    rm -f "$DATA/applications/$LEGACY_ID.desktop"
    for s in 48 64 128 256 512; do rm -f "$DATA/icons/hicolor/${s}x${s}/apps/$LEGACY_ID.png"; done
}

if [ "$1" = "--remove" ]; then
    remove_legacy
    rm -f "$DATA/applications/$ID.desktop"
    for s in 48 64 128 256 512; do rm -f "$DATA/icons/hicolor/${s}x${s}/apps/$ID.png"; done
    echo "Removed."
    exit 0
fi

remove_legacy
for s in 48 64 128 256 512; do
    install -Dm644 "$ROOT/data/icons/hicolor/${s}x${s}/apps/$ID.png" "$DATA/icons/hicolor/${s}x${s}/apps/$ID.png"
done
mkdir -p "$DATA/applications"
sed "s|^Exec=deluxe-sticky-notes|Exec=env PYTHONPATH=$ROOT python3 -m stickynotes|" "$ROOT/data/$ID.desktop" > "$DATA/applications/$ID.desktop"
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$DATA/icons/hicolor" 2>/dev/null || true
command -v update-desktop-database >/dev/null && update-desktop-database -q "$DATA/applications" 2>/dev/null || true
echo "Installed. \"Deluxe Sticky Notes\" now appears in the app menu."
