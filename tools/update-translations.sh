#!/bin/sh
# Çevrilecek metinleri koddan çıkarır, po/tr.po'yu günceller ve derlenmiş .mo dosyasını üretir.
# Yeni bir dil eklemek için: msginit -i po/sticky-notes.pot -o po/<dil>.po -l <dil>
set -e
cd "$(dirname "$0")/.."
xgettext --from-code=UTF-8 -L Python -k_ -kN_ -kngettext:1,2 --package-name=sticky-notes \
    --msgid-bugs-address=https://github.com/Snemege/deluxe-sticky-notes/issues --no-location -o po/sticky-notes.pot stickynotes/*.py
for po in po/*.po; do
    lang=$(basename "$po" .po)
    msgmerge --update --backup=none --quiet "$po" po/sticky-notes.pot
    msgattrib --no-obsolete -o "$po" "$po"      # koddan kalkan metinleri temizle
    mkdir -p "locale/$lang/LC_MESSAGES"
    msgfmt --check -o "locale/$lang/LC_MESSAGES/sticky-notes.mo" "$po"
    msgfmt --statistics -o /dev/null "$po"
done
