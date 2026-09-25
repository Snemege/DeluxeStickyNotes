"""Üst çubukta (sistem tepsisi) uygulama ikonu: StatusNotifierItem + dbusmenu.

GNOME'da bunun görünmesi için AppIndicator uzantısı gerekir. Uzantı yoksa ya da sonradan
açılırsa, StatusNotifierWatcher görününce kendini otomatik kaydeder.
"""
import os

from gi.repository import GdkPixbuf, Gio, GLib

from .i18n import _
from .store import APP_ID

ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"

ITEM_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="u" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
    <signal name="NewIcon"/>
    <signal name="NewStatus"><arg type="s"/></signal>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
      <arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" direction="in"/><arg type="as" direction="in"/>
      <arg type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/>
      <arg type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/>
    </method>
    <method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
    <method name="AboutToShowGroup">
      <arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})"/><arg type="a(ias)"/>
    </signal>
    <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
    <signal name="ItemActivationRequested"><arg type="i"/><arg type="u"/></signal>
  </interface>
</node>
"""


class Tray:
    def __init__(self, app):
        self.app = app
        self.conn = None
        # id -> (etiket, çağrılacak işlev)  (0 kök menüdür)
        self.items = {
            1: (_("Show all notes"), app.show_main),
            2: (_("New note"), app.new_note),
            3: (_("Settings"), self._open_settings),
            4: (_("Quit"), app.quit_app),
        }
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._icon_dir = os.path.join(root, "data", "icons", "hicolor")
        self._pixmaps = self._load_pixmaps()

    def _load_pixmaps(self):
        """İkonu doğrudan piksel verisi olarak da gönderir (ARGB32, ağ bayt sırası).

        Tema ikonu çözülemezse (uygulama kurulmamışsa) tepsi yine de doğru ikonu gösterir.
        IconThemePath bilerek boş bırakılır: AppIndicator uzantısı doluysa yalnızca o klasöre
        bakar ve index.theme olmadığı için ikonu bulamayıp "yükleniyor" simgesi gösterir.
        """
        result = []
        for size in (32, 64):
            path = os.path.join(self._icon_dir, f"{size}x{size}", "apps", f"{APP_ID}.png")
            if not os.path.exists(path):
                path = os.path.join(self._icon_dir, "128x128", "apps", f"{APP_ID}.png")
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(path, size, size)
            except GLib.Error:
                continue
            pixbuf = pixbuf if pixbuf.get_has_alpha() else pixbuf.add_alpha(False, 0, 0, 0)
            rgba, stride = pixbuf.get_pixels(), pixbuf.get_rowstride()
            width, height = pixbuf.get_width(), pixbuf.get_height()
            out = bytearray()
            for y in range(height):
                row = rgba[y * stride:y * stride + width * 4]
                for x in range(0, width * 4, 4):
                    out += bytes((row[x + 3], row[x], row[x + 1], row[x + 2]))   # A, R, G, B
            result.append((width, height, bytes(out)))
        return result

    def start(self):
        try:
            self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            item = Gio.DBusNodeInfo.new_for_xml(ITEM_XML).interfaces[0]
            menu = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
            self.conn.register_object(ITEM_PATH, item, self._on_item_call, self._on_item_prop, None)
            self.conn.register_object(MENU_PATH, menu, self._on_menu_call, self._on_menu_prop, None)
        except GLib.Error:
            return
        # Watcher (AppIndicator uzantısı) her göründüğünde yeniden kaydol
        Gio.bus_watch_name(Gio.BusType.SESSION, "org.kde.StatusNotifierWatcher",
                           Gio.BusNameWatcherFlags.NONE, self._register, None)

    def _register(self, *_args):
        # "/" ile başlayan yol verilirse watcher gönderenin bağlantı adını kullanır
        self.conn.call(
            "org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher",
            "RegisterStatusNotifierItem", GLib.Variant("(s)", (ITEM_PATH,)), None,
            Gio.DBusCallFlags.NONE, -1, None, None, None)

    def _open_settings(self):
        self.app.show_main()
        self.app.show_settings()

    # ---- StatusNotifierItem ----
    def _on_item_prop(self, _conn, _sender, _path, _iface, name):
        props = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", APP_ID),
            "Title": GLib.Variant("s", _("Deluxe Sticky Notes")),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("u", 0),
            "IconName": GLib.Variant("s", APP_ID),
            "IconPixmap": GLib.Variant("a(iiay)", self._pixmaps),
            "IconThemePath": GLib.Variant("s", ""),
            "Menu": GLib.Variant("o", MENU_PATH),
            "ItemIsMenu": GLib.Variant("b", False),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", ("", [], _("Deluxe Sticky Notes"),
                                                     _("Click: show all notes"))),
        }
        return props.get(name)

    def _on_item_call(self, _conn, _sender, _path, _iface, method, _params, invocation):
        if method == "Activate":
            GLib.idle_add(self.app.show_main)          # sol tık: tüm notlar
        elif method == "SecondaryActivate":
            GLib.idle_add(self.app.new_note)           # orta tık: yeni not
        invocation.return_value(None)

    # ---- dbusmenu ----
    def _item_props(self, item_id):
        label = self.items[item_id][0]
        return {"label": GLib.Variant("s", label), "enabled": GLib.Variant("b", True),
                "visible": GLib.Variant("b", True)}

    def _on_menu_prop(self, _conn, _sender, _path, _iface, name):
        return {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }.get(name)

    def _on_menu_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "GetLayout":
            children = [GLib.Variant("(ia{sv}av)", (i, self._item_props(i), [])) for i in self.items]
            root = (0, {"children-display": GLib.Variant("s", "submenu")}, children)
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (1, root)))
        elif method == "GetGroupProperties":
            ids = params.unpack()[0] or list(self.items)
            invocation.return_value(GLib.Variant(
                "(a(ia{sv}))", ([(i, self._item_props(i)) for i in ids if i in self.items],)))
        elif method == "GetProperty":
            item_id, name = params.unpack()[:2]
            value = self._item_props(item_id).get(name) if item_id in self.items else None
            invocation.return_value(GLib.Variant("(v)", (value or GLib.Variant("s", ""),)))
        elif method == "Event":
            item_id, event = params.unpack()[:2]
            if event == "clicked" and item_id in self.items:
                GLib.idle_add(self.items[item_id][1])
            invocation.return_value(None)
        elif method == "EventGroup":
            for item_id, event, _data, _ts in params.unpack()[0]:
                if event == "clicked" and item_id in self.items:
                    GLib.idle_add(self.items[item_id][1])
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_value(None)
