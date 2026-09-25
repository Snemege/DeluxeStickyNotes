# GNOME Sticky Notes

GNOME Shell 50 eklentisi. Notlar masaüstü katmanında görünür; masaüstüne sağ tıklayıp **Not ekle** ile yeni not eklenir. Notlar kartın her yerinden sürüklenebilir, başlığa çift tıklayınca sadece başlık kalır (tekrar çift tıkla, açılır). Ayrıca, metinlerini düzenleyebilir, renklerini değiştirebilir ve silebilirsin. Kayıtlar `~/.local/share/gnome-sticky-notes/notes.json` dosyasında tutulur.

## Kurulum

```sh
./install.sh
```

Fedora GNOME Wayland oturumu için hazırlanmıştır.

## Deneme

Masaüstüne sağ tıkla → **Not ekle**, nota yaz, kartın her yerinden sürükle. Başlığa çift tıklayınca not kapanır. Renk düğmesine tıkla. Oturumu kapatıp açtıktan sonra notların kaldığını kontrol et.

## Kaldırma

```sh
gnome-extensions disable gnome-sticky-notes@vex.local
rm -r ~/.local/share/gnome-shell/extensions/gnome-sticky-notes@vex.local
```
