import os

import gi

__version__ = "0.1.0"

# GNOME/Wayland uygulamaların kendi pencere konumunu ayarlamasına izin vermez, bu yüzden notlar
# eski yerlerine dönemez. Notların yerini hatırlayabilmek için XWayland (X11) tercih edilir;
# X11 yoksa kendiliğinden Wayland'e düşer. Saf Wayland için: STICKYNOTES_WAYLAND=1
if not os.environ.get("STICKYNOTES_WAYLAND"):
    os.environ.setdefault("GDK_BACKEND", "x11,wayland")

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
