import os

from gi.repository import Gio, GLib

from .i18n import _
from .store import APP_ID


def in_flatpak():
    return os.path.exists("/.flatpak-info")


def _autostart_path():
    config = os.environ.get("XDG_CONFIG_HOME") or GLib.get_user_config_dir()
    return os.path.join(config, "autostart", f"{APP_ID}.desktop")


def _portal_request(enabled):
    """Flatpak içinde otomatik başlatma Background portalı üzerinden istenir."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        options = {
            "autostart": GLib.Variant("b", enabled),
            "background": GLib.Variant("b", enabled),
            "commandline": GLib.Variant("as", ["sticky-notes", "--background"]),
            "reason": GLib.Variant("s", _("Runs in the background for alarms and open notes")),
        }
        bus.call_sync(
            "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Background", "RequestBackground",
            GLib.Variant("(sa{sv})", ("", options)), None, Gio.DBusCallFlags.NONE, -1, None,
        )
        return True
    except GLib.Error:
        return False


def set_autostart(enabled):
    """Oturum açılışında `--background` ile başlatmayı açar/kapatır. Başarıyı döndürür."""
    if in_flatpak():
        return _portal_request(enabled)
    path = _autostart_path()
    if not enabled:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return True
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "[Desktop Entry]\nType=Application\nName=Deluxe Sticky Notes\nName[tr]=Deluxe Yapışkan Notlar\n"
                f"Exec=env PYTHONPATH={root} python3 -m stickynotes --background\n"
                "X-GNOME-Autostart-enabled=true\nNoDisplay=true\n"
            )
        return True
    except OSError:
        return False
