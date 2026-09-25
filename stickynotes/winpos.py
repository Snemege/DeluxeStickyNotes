"""Pencere konumunu okuma/ayarlama (yalnızca X11/XWayland arka ucunda).

GTK4 pencereyi taşıma API'sini kaldırdı; X11'de doğrudan Xlib ile yapılır. Wayland arka ucunda
işlevler None/False döndürür ve notlar konumlarını hatırlayamaz.
"""
import ctypes
import warnings

import gi
from gi.repository import Gio, GLib

try:
    gi.require_version("GdkX11", "4.0")
    from gi.repository import GdkX11
except (ValueError, ImportError):
    GdkX11 = None

_state = {"tried": False, "x11": None}


class _XClientMessage(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("window", ctypes.c_ulong),
                ("message_type", ctypes.c_ulong), ("format", ctypes.c_int),
                ("data", ctypes.c_long * 5)]


class _X11:
    def __init__(self):
        lib = ctypes.CDLL("libX11.so.6")
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.dpy = lib.XOpenDisplay(None)
        if not self.dpy:
            raise OSError("Could not connect to the X server")
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XMoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int]
        lib.XFlush.argtypes = [ctypes.c_void_p]
        lib.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XTranslateCoordinates.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong)]
        lib.XInternAtom.restype = ctypes.c_ulong
        lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        lib.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long,
                                   ctypes.c_void_p]
        self.lib = lib
        self.root = lib.XDefaultRootWindow(self.dpy)

    def set_motif_functions(self, xid, allow_all):
        """_MOTIF_WM_HINTS: pencere yöneticisine taşıma/boyutlandırma/kapatma/küçültme/büyütme izni
        verilip verilmediğini bildirir (izin yoksa Alt+sürükle, klavye ve Alt+F4 de çalışmaz)."""
        lib = self.lib
        atom = lib.XInternAtom(self.dpy, b"_MOTIF_WM_HINTS", 0)
        # flags=FUNCTIONS(1)|DECORATIONS(2), functions=ALL(1) ya da hiçbiri(0), decorations=0 (yok),
        # input_mode, status. Süsleme "yok" olarak açıkça yazılmalı: GTK kendi başlık çubuğunu çizer;
        # yazılmazsa pencere yöneticisi bir de sunucu tarafı başlık çubuğu ekleyip pencereyi kaydırır.
        hints = (ctypes.c_long * 5)(3, 1 if allow_all else 0, 0, 0, 0)
        lib.XChangeProperty(self.dpy, xid, atom, atom, 32, 0, ctypes.byref(hints), 5)
        lib.XFlush(self.dpy)

    def set_wm_state(self, xid, names, add):
        """EWMH _NET_WM_STATE_* durumlarını ekler/kaldırır (en fazla iki tanesi aynı anda)."""
        lib = self.lib
        event = _XClientMessage()
        event.type = 33                                   # ClientMessage
        event.window = xid
        event.message_type = lib.XInternAtom(self.dpy, b"_NET_WM_STATE", 0)
        event.format = 32
        event.data[0] = 1 if add else 0                   # _NET_WM_STATE_ADD / REMOVE
        for i, name in enumerate(names[:2], start=1):
            event.data[i] = lib.XInternAtom(self.dpy, name.encode(), 0)
        event.data[3] = 1                                 # kaynak: normal uygulama
        mask = (1 << 20) | (1 << 19)                      # SubstructureRedirect | SubstructureNotify
        lib.XSendEvent(self.dpy, self.root, 0, mask, ctypes.byref(event))
        lib.XFlush(self.dpy)

    def position(self, xid):
        x, y, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
        self.lib.XTranslateCoordinates(self.dpy, xid, self.root, 0, 0,
                                       ctypes.byref(x), ctypes.byref(y), ctypes.byref(child))
        return x.value, y.value

    def move(self, xid, x, y):
        self.lib.XMoveWindow(self.dpy, xid, x, y)
        self.lib.XFlush(self.dpy)



def bounds_from_state(monitors, logical):
    """Mutter GetCurrentState verisinden tüm monitörleri kapsayan (x0, y0, x1, y1); yoksa None."""
    sizes = {}
    for spec, modes, _mprops in monitors:
        for _id, w, h, _rate, _scale, _scales, mode_props in modes:
            if mode_props.get("is-current"):
                sizes[spec[0]] = (w, h)
    rects = []
    for x, y, scale, transform, _primary, specs, _lprops in logical:
        w, h = sizes.get(specs[0][0], (0, 0))
        if transform in (1, 3, 5, 7):       # 90/270 derece dönük
            w, h = h, w
        if w and h and scale:
            rects.append((x, y, x + int(w / scale), y + int(h / scale)))
    if not rects:
        return None
    bounds = (min(r[0] for r in rects), min(r[1] for r in rects),
              max(r[2] for r in rects), max(r[3] for r in rects))
    # Saçma değerlere güvenme (sınırlamaktansa sınırlamamak daha güvenli)
    if bounds[2] - bounds[0] < 640 or bounds[3] - bounds[1] < 480:
        return None
    return bounds


def _screen_bounds():
    """XWayland ekran boyutunu 0x0 bildirdiği için monitör yerleşimi GNOME Mutter'ın
    DisplayConfig servisinden okunur; alınamazsa None (konum sınırlanmaz)."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync(
            "org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
            "org.gnome.Mutter.DisplayConfig", "GetCurrentState", None, None,
            Gio.DBusCallFlags.NONE, 1500, None)
        _serial, monitors, logical, _props = reply.unpack()
        return bounds_from_state(monitors, logical)
    except (GLib.Error, ValueError, TypeError, IndexError):
        return None


def _x11():
    if not _state["tried"]:
        _state["tried"] = True
        try:
            _state["x11"] = _X11()
        except OSError:
            _state["x11"] = None
    return _state["x11"]


def _xid(window):
    if GdkX11 is None:
        return None
    surface = window.get_surface()
    if surface is None or not isinstance(surface, GdkX11.X11Surface):
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return surface.get_xid()


def supported(window):
    return _xid(window) is not None and _x11() is not None


def get_position(window):
    """(x, y) ya da desteklenmiyorsa None."""
    xid, x11 = _xid(window), _x11()
    if xid is None or x11 is None:
        return None
    return x11.position(xid)


def set_position(window, x, y):
    """Pencereyi ekran içinde kalacak şekilde taşır. Başarıyı döndürür."""
    xid, x11 = _xid(window), _x11()
    if xid is None or x11 is None:
        return False
    bounds = _screen_bounds()
    if bounds:  # monitör çıkarılmış/çözünürlük değişmişse pencere ekran dışında kalmasın
        x = max(bounds[0] - 40, min(int(x), bounds[2] - 120))
        y = max(bounds[1], min(int(y), bounds[3] - 60))
    x11.move(xid, int(x), int(y))
    return True


def set_wm_state(window, names, add=True):
    """Pencereye EWMH durumu ekler/kaldırır. Başarıyı döndürür (Wayland'de False)."""
    xid, x11 = _xid(window), _x11()
    if xid is None or x11 is None:
        return False
    x11.set_wm_state(xid, names, add)
    return True


def set_functions(window, allowed):
    """allowed=False: pencere yöneticisi pencereyi taşıyamaz/boyutlandıramaz/kapatamaz/küçültemez.
    Başarıyı döndürür (Wayland'de False)."""
    xid, x11 = _xid(window), _x11()
    if xid is None or x11 is None:
        return False
    x11.set_motif_functions(xid, allowed)
    return True


def allowed_actions(window):
    """Pencere yöneticisinin izin verdiği eylemler (_NET_WM_ACTION_* adları)."""
    import subprocess
    xid = _xid(window)
    if xid is None:
        return []
    out = subprocess.run(["xprop", "-id", str(xid), "_NET_WM_ALLOWED_ACTIONS"], capture_output=True,
                         text=True).stdout
    return [t.strip() for t in out.split("=", 1)[-1].split(",") if t.strip().startswith("_NET_")]


def set_skip_taskbar(window, skip=True):
    """Pencereyi görev çubuğu/dock'ta saydırma (GNOME uygulamayı "çalışıyor" göstermez)."""
    return set_wm_state(window, ["_NET_WM_STATE_SKIP_TASKBAR", "_NET_WM_STATE_SKIP_PAGER"], skip)


def set_layer(window, layer):
    """"above": her zaman üstte, "below": diğer pencerelerin altında, "normal": sıradan."""
    ok = set_wm_state(window, ["_NET_WM_STATE_ABOVE"], layer == "above")
    return set_wm_state(window, ["_NET_WM_STATE_BELOW"], layer == "below") and ok


def wm_states(window):
    """Pencerenin şu anki _NET_WM_STATE atom adları (test/hata ayıklama için)."""
    import subprocess
    xid = _xid(window)
    if xid is None:
        return []
    out = subprocess.run(["xprop", "-id", str(xid), "_NET_WM_STATE"], capture_output=True, text=True).stdout
    return [t.strip() for t in out.split("=", 1)[-1].split(",") if t.strip().startswith("_NET_")]
