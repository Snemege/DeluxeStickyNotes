import os
import sys
import tempfile

# Testler sistem diline bağlı olmasın; çeviri testleri Türkçeyi kendisi yükler
os.environ.setdefault("STICKYNOTES_LANG", "en")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def isolate_dirs():
    """Testler gerçek notlara/ayarlara dokunmasın: veri ve yapılandırma geçici dizinlere gider."""
    os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp(prefix="sn-data-")
    os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="sn-config-")


def has_display():
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def screen_is_blank():
    """Ekran koruyucu/kilit aktifken pencereler yerleşmez (boyut 0x0, kare saati durur); arayüz
    testleri bu durumda sahte hata vermesin diye atlanır."""
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver",
                              "GetActive", None, None, Gio.DBusCallFlags.NONE, 1000, None)
        return bool(reply.unpack()[0])
    except Exception:  # noqa: BLE001 - ScreenSaver servisi yoksa ekranın karardığını varsayma
        return False
