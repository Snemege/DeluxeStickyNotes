"""Global kısayollar (xdg-desktop-portal GlobalShortcuts).

Uygulama açık pencere olmadan da Ctrl+Alt+N (yeni not) ve Ctrl+Alt+A (tüm notlar) ile
çağrılabilir. Portal, uygulamayı masaüstü kısayolundan/Flatpak'tan başlatıldığında tanır;
terminalden başlatılırsa kısayol kaydı başarısız olabilir.
"""
import itertools

from gi.repository import Gio, GLib

from .i18n import _

PORTAL = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
IFACE = "org.freedesktop.portal.GlobalShortcuts"

SHORTCUTS = [
    ("new-note", _("Create a new note"), "CTRL+ALT+N"),
    ("show-all", _("Show all notes"), "CTRL+ALT+A"),
]


class GlobalShortcuts:
    def __init__(self, app):
        self.app = app
        self.conn = None
        self.session = None
        self._activated_sub = 0
        self._tokens = itertools.count(1)
        self.status = "off"        # off | connecting | ready | error: ...

    def start(self):
        if self.conn is not None:
            return
        try:
            self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as e:
            self.status = f"error: {e.message}"
            return
        self.status = "connecting"
        self._request("CreateSession", lambda token: GLib.Variant("(a{sv})", ({
            "handle_token": GLib.Variant("s", token),
            "session_handle_token": GLib.Variant("s", "stickynotes_session"),
        },)), self._on_session)

    def stop(self):
        if self.conn and self.session:
            self.conn.call(PORTAL, self.session, "org.freedesktop.portal.Session", "Close", None, None,
                           Gio.DBusCallFlags.NONE, -1, None, None, None)
        if self.conn and self._activated_sub:
            self.conn.signal_unsubscribe(self._activated_sub)
        self.conn, self.session, self._activated_sub = None, None, 0
        self.status = "off"

    def _request(self, method, build_params, callback):
        """Portal isteği gönderir; Request.Response sinyalini bekleyip callback(code, results) çağırır."""
        token = f"stickynotes{next(self._tokens)}"
        sender = self.conn.get_unique_name()[1:].replace(".", "_")
        path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        subscription = [0]

        def on_response(conn, _sender, _path, _iface, _signal, params, *_):
            conn.signal_unsubscribe(subscription[0])
            code, results = params.unpack()
            callback(code, results)

        # Yanıt, çağrı dönmeden gelebilir; bu yüzden önce abone olunur
        subscription[0] = self.conn.signal_subscribe(
            PORTAL, "org.freedesktop.portal.Request", "Response", path, None,
            Gio.DBusSignalFlags.NONE, on_response)

        def on_call_done(conn, result):
            try:
                conn.call_finish(result)
            except GLib.Error as e:
                conn.signal_unsubscribe(subscription[0])
                self.status = f"error: {e.message}"

        self.conn.call(PORTAL, PATH, IFACE, method, build_params(token), None,
                       Gio.DBusCallFlags.NONE, -1, None, on_call_done)

    def _on_session(self, code, results):
        if code != 0:
            self.status = "error: could not open a session"
            return
        self.session = results.get("session_handle")
        self._activated_sub = self.conn.signal_subscribe(
            PORTAL, IFACE, "Activated", PATH, None, Gio.DBusSignalFlags.NONE, self._on_activated)
        shortcuts = [(sid, {"description": GLib.Variant("s", desc),
                            "preferred_trigger": GLib.Variant("s", trigger)})
                     for sid, desc, trigger in SHORTCUTS]
        self._request("BindShortcuts", lambda token: GLib.Variant(
            "(oa(sa{sv})sa{sv})",
            (self.session, shortcuts, "", {"handle_token": GLib.Variant("s", token)})),
            self._on_bound)

    def _on_bound(self, code, _results):
        self.status = "ready" if code == 0 else "error: shortcuts were not assigned"

    def _on_activated(self, _conn, _sender, _path, _iface, _signal, params, *_):
        _session, shortcut_id, _timestamp, _options = params.unpack()
        if shortcut_id == "new-note":
            GLib.idle_add(self.app.new_note)
        elif shortcut_id == "show-all":
            GLib.idle_add(self.app.show_main)
