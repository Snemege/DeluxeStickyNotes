#!/usr/bin/env bash
set -euo pipefail

uuid='gnome-sticky-notes@vex.local'
source_dir="$(cd "$(dirname "$0")" && pwd)"
bundle_dir="$(mktemp -d)"
trap 'rm -rf "$bundle_dir"' EXIT

gnome-extensions pack "$source_dir" --out-dir "$bundle_dir"
gnome-extensions install --force "$bundle_dir/$uuid.shell-extension.zip"
if gnome-extensions enable "$uuid"; then
  printf 'GNOME Sticky Notes kuruldu ve etkinleştirildi. Masaüstüne sağ tıklayıp "Not ekle" de.\n'
else
  printf 'Eklenti kuruldu; çalışan GNOME oturumu henüz eklentiyi tanımıyor. Oturumu kapatıp açtıktan sonra gnome-extensions enable %s komutunu çalıştır.\n' "$uuid"
fi
