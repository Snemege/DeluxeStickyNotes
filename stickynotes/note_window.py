import time

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from . import sound, winpos
from .i18n import _
from .store import COLORS, SNOOZE_MINUTES, next_alarm_time

TAGS = {
    "bold": {"weight": Pango.Weight.BOLD},
    "italic": {"style": Pango.Style.ITALIC},
    "underline": {"underline": Pango.Underline.SINGLE},
    "strikethrough": {"strikethrough": True},
    # işaretlenmiş (☑) yapılacaklar satırı
    "done": {"strikethrough": True, "foreground": "#7a7a7a"},
    # satır başındaki •/☐/☑ karakterini büyütür
    "glyph": {"scale": 1.7},
}

FONT_SIZES = [11, 12, 13, 14, 16, 18, 20, 24, 28, 32]  # px
DEFAULT_FONT_SIZE = 16
# Seçili metnin boyutu: her boyut için bir etiket ("size-18" gibi), kayıtta da bu adla saklanır
SIZE_TAGS = {f"size-{px}": px for px in FONT_SIZES}
for _name, _px in SIZE_TAGS.items():
    TAGS[_name] = {"size-points": _px * 0.75}      # CSS px -> pt (96 dpi)
RING_TICKS = 135  # 45 ms adım -> ~6 sn, alarm sesinin süresi kadar
TOGGLE_GUARD = 0.6   # küçült/büyült sonrası bu kadar saniye başlıktaki basışlar yutulur
RING_JITTER = 7   # alarm çalarken pencere boyutunun oynama miktarı (px)
MIN_SIZE = (300, 46)  # başlığa küçültülebilmesi için asgari boyut

# Sistem ikon teması bu ikonları içermediği için yazı etiketleri kullanılıyor.
FORMAT_BUTTONS = [
    ("bold", "<b>B</b>", _("Bold (Ctrl+B)")),
    ("italic", "<i>I</i>", _("Italic (Ctrl+I)")),
    ("underline", "<u>U</u>", _("Underline (Ctrl+U)")),
    ("strikethrough", "<s>S</s>", _("Strikethrough (Ctrl+Shift+X)")),
]

PREFIXES = {"bullet": "• ", "check": "☐ "}
CHECK_GLYPHS = ("☐", "☑")


def list_kind(line):
    if line.startswith("• "):
        return "bullet"
    if line[:2] in ("☐ ", "☑ "):
        return "check"
    return None


NAV_KEYS = {
    Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_Home, Gdk.KEY_End,
    Gdk.KEY_Page_Up, Gdk.KEY_Page_Down, Gdk.KEY_BackSpace, Gdk.KEY_Delete,
}


def serialize_tags(buf):
    """Biçim aralıklarını [[ad, başlangıç, bitiş], ...] olarak döndürür (karakter ofseti)."""
    result = []
    for name in TAGS:
        tag = buf.get_tag_table().lookup(name)
        it = buf.get_start_iter()
        while True:
            if not it.has_tag(tag):
                if not it.forward_to_tag_toggle(tag):
                    break
            start = it.get_offset()
            it.forward_to_tag_toggle(tag)
            result.append([name, start, it.get_offset()])
            if it.is_end():
                break
    return result


def load_into_buffer(buf, text, tags):
    buf.set_text(text)
    for name, start, end in tags:
        if name in TAGS:
            buf.apply_tag_by_name(name, buf.get_iter_at_offset(start), buf.get_iter_at_offset(end))


class NoteWindow(Adw.ApplicationWindow):
    def __init__(self, app, store, note_id):
        note = store.notes[note_id]
        super().__init__(application=app, default_width=note["width"], default_height=note["height"])
        # libadwaita varsayılan olarak 360x200'den küçülmeye izin vermez; başlığa küçültme için gerekli
        self.set_size_request(*MIN_SIZE)
        self._min_id = 0
        self._layer_init = False
        self.font_size = None
        self.app = app
        self.store = store
        self.note_id = note_id
        self.color = None
        self._loading = False
        self._suspend_save = False
        self._syncing = False
        self._pending = {}
        self._prev_state = {}
        self._plain = False
        self._collapsed = False
        self._ringing = False
        self._ring_id = 0
        self._ring_ticks = 0
        self._chrome_id = 0
        self._chrome_on = True       # düğmeler açık mı; nota tıklayınca açılır, odak başka yere geçince kapanır
        self._show_id = 0            # başlığa ilk basıştan sonra düğmeleri geciktirmeli göstermek için
        self._last_toggle = 0.0      # son küçült/büyült zamanı (time.monotonic)
        self._pointer_inside = False # fare notun üstünde mi (alarm sallanmasını durdurmak için)
        self._locked = bool(note.get("locked"))   # kilitli not: taşınamaz, boyutlanamaz, kapanamaz, düzenlenemez
        self._closed = False
        self._pos_last = None
        self._ring_base = None
        self._expanded_height = note["height"]
        self._expanded_width = note["width"]
        self.fmt_buttons = {}

        self._build_ui()
        self._build_actions()

        self._loading = True
        load_into_buffer(self.buffer, note["text"], note["tags"])
        self._apply_glyph_tags()
        self.buffer.place_cursor(self.buffer.get_start_iter())
        self.buffer.set_enable_undo(False)
        self.buffer.set_enable_undo(True)
        self._loading = False
        self._update_title()
        self.refresh_alarm()
        self.set_font_size(note.get("font_size", DEFAULT_FONT_SIZE), save=False)
        self.set_color(note["color"], save=False)
        if note.get("collapsed"):
            self.set_collapsed(True, save=False)
        self._apply_lock()

        self.connect("close-request", self._on_close)
        self.connect("map", self._on_map)
        self.connect("notify::is-active", self._schedule_chrome)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: setattr(self, "_pointer_inside", True))
        motion.connect("leave", lambda *_: setattr(self, "_pointer_inside", False))
        self.add_controller(motion)
        self._popover.connect("closed", self._schedule_chrome)
        self._alarm_popover.connect("closed", self._schedule_chrome)
        self._update_chrome()

    # ---- arayüz ----
    def _build_ui(self):
        header = Adw.HeaderBar()
        # Küçült/büyüt/kapat yerine sadece kapat düğmesi (küçültmeyi kendi düğmemiz yapar)
        header.set_decoration_layout(":close")
        self._header = header
        header.add_css_class("note-header")
        self.title_label = Gtk.Label(ellipsize=Pango.EllipsizeMode.END, single_line_mode=True)
        self.title_label.add_css_class("heading")
        header.set_title_widget(self.title_label)
        header_click = Gtk.GestureClick()
        header_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        header_click.connect("pressed", self._on_header_pressed, header)
        header.add_controller(header_click)

        self._new_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("New note (Ctrl+N)"))
        self._new_btn.set_action_name("app.new-note")
        header.pack_start(self._new_btn)

        self._menu_btn = self._build_menu()
        header.pack_end(self._menu_btn)
        header.pack_end(self._build_alarm())
        self._snooze_btn = Gtk.Button(label=_("Snooze {n} min").format(n=SNOOZE_MINUTES), visible=False,
                                      css_classes=["suggested-action"])
        self._snooze_btn.connect("clicked", lambda _b: self.app.snooze_note(self.note_id))
        header.pack_end(self._snooze_btn)
        self._collapse_btn = Gtk.Button(icon_name="pan-up-symbolic",
                                        tooltip_text=_("Collapse to the title (or double-click the title)"))
        self._collapse_btn.connect("clicked", lambda _b: self.set_collapsed(not self._collapsed))
        header.pack_end(self._collapse_btn)

        self.buffer = Gtk.TextBuffer()
        for name, props in TAGS.items():
            self.buffer.create_tag(name, **props)
        self.buffer.connect("changed", self._on_changed)
        self.buffer.connect("insert-text", self._on_insert_before)
        self.buffer.connect_after("insert-text", self._on_insert_after)
        self.buffer.connect_after("apply-tag", self._on_tag_changed)
        self.buffer.connect_after("remove-tag", self._on_tag_changed)
        self.buffer.connect("notify::cursor-position", lambda *_: self._sync_buttons())
        self.buffer.connect("mark-set", lambda *_: self._sync_buttons())

        self.textview = Gtk.TextView(
            buffer=self.buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR,
            left_margin=12, right_margin=12, top_margin=8, bottom_margin=8,
            vexpand=True, hexpand=True,
        )
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key_pressed)
        self.textview.add_controller(keys)
        click = Gtk.GestureClick()
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", self._on_click_pressed)
        self.textview.add_controller(click)

        scrolled = Gtk.ScrolledWindow(child=self.textview, hscrollbar_policy=Gtk.PolicyType.NEVER)

        bar = Gtk.Box(spacing=2, halign=Gtk.Align.CENTER, margin_top=4, margin_bottom=6)
        bar.add_css_class("note-bar")
        for name, markup, tip in FORMAT_BUTTONS:
            btn = Gtk.ToggleButton(child=Gtk.Label(label=markup, use_markup=True), tooltip_text=tip)
            btn.add_css_class("flat")
            btn.connect("toggled", self._on_fmt_button, name)
            bar.append(btn)
            self.fmt_buttons[name] = btn
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4))
        for kind, glyph, tip in [
            ("bullet", "<span size='x-large'>•</span>", _("Bullet list (Ctrl+Shift+L)")),
            ("check", "<span size='x-large'>☑</span>", _("To-do list (Ctrl+Shift+K)")),
        ]:
            btn = Gtk.Button(child=Gtk.Label(label=glyph, use_markup=True), tooltip_text=tip)
            btn.add_css_class("flat")
            btn.set_detailed_action_name(f"win.list::{kind}")
            bar.append(btn)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4))
        for direction, label, tip in [
            ("out", "A−", _("Make selected text smaller (Ctrl+-)")),
            ("in", "A+", _("Make selected text larger (Ctrl++)")),
        ]:
            btn = Gtk.Button(label=label, tooltip_text=tip)
            btn.add_css_class("flat")
            btn.set_detailed_action_name(f"win.zoom::{direction}")
            bar.append(btn)

        # Sağ tık menüsü: metin alanında (standart menünün sonuna) ve başlıkta
        context = Gio.Menu()
        actions_section = Gio.Menu()
        actions_section.append(_("Pin"), "win.pin")
        actions_section.append(_("Delete note…"), "win.delete")
        colors = Gio.Menu()
        for key, (label, _bg) in COLORS.items():
            colors.append(_(label), f"win.color::{key}")
        actions_section.append_submenu(_("Change color"), colors)
        context.append_section(None, actions_section)
        self._lock_section = Gio.Menu()          # "Lock note" / "Unlock note" (duruma göre yeniden doldurulur)
        context.append_section(None, self._lock_section)
        nav_section = Gio.Menu()
        nav_section.append(_("New note"), "app.new-note")
        nav_section.append(_("Show all notes"), "app.show-all")
        context.append_section(None, nav_section)
        self.textview.set_extra_menu(context)
        # Üst kutu: başlık çubuğu (ya da kilitliyken düz başlık şeridi) + ayırıcı çizgi
        self._top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._context_popover = Gtk.PopoverMenu(menu_model=context, has_arrow=False)
        self._context_popover.set_parent(self._top)
        right_click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right_click.connect("pressed", self._on_header_right_click)
        self._top.add_controller(right_click)
        # Kilitliyken başlık çubuğunun yerine geçer: sürükleme tutamağı ve düğmeleri yoktur
        self._lock_title = Gtk.Label(ellipsize=Pango.EllipsizeMode.END, single_line_mode=True,
                                     css_classes=["heading"])
        self._lock_alarm = Gtk.Label(css_classes=["alarm-pill"], visible=False, margin_end=10,
                                     valign=Gtk.Align.CENTER)
        self._lock_strip = Gtk.CenterBox(css_classes=["note-lock-strip"])
        self._lock_strip.set_center_widget(self._lock_title)
        self._lock_strip.set_end_widget(self._lock_alarm)

        self._scrolled = scrolled
        self._bar = bar
        view = Adw.ToolbarView(content=scrolled)
        self._view = view
        dismiss = Gtk.GestureClick()
        dismiss.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        dismiss.connect("pressed", self._on_press)   # nota tıklayınca alarm susar, düğmeler açılır
        view.add_controller(dismiss)
        self._top.append(header)
        self._top.append(Gtk.Separator(css_classes=["note-sep"]))  # başlığı ayıran çizgi
        view.add_top_bar(self._top)
        view.add_bottom_bar(bar)
        view.set_top_bar_style(Adw.ToolbarStyle.FLAT)
        view.set_bottom_bar_style(Adw.ToolbarStyle.FLAT)
        self.set_content(view)

    def _build_menu(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=8,
                      margin_bottom=8, margin_start=8, margin_end=8)
        swatches = Gtk.Box(spacing=6)
        for name, (label, _bg) in COLORS.items():
            sw = Gtk.Button(tooltip_text=_(label))
            sw.add_css_class("swatch")
            sw.add_css_class(f"swatch-{name}")
            sw.connect("clicked", self._on_swatch, name)
            swatches.append(sw)
        box.append(swatches)
        box.append(Gtk.Separator())
        self._layer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._layer_box.append(Gtk.Label(label=_("Layer"), xalign=0, css_classes=["dim-label", "caption"]))
        self._layer_buttons, first = {}, None
        for key, label in (("normal", _("Normal")), ("above", _("Always on top")),
                           ("below", _("Always at the bottom (like the desktop)"))):
            radio = Gtk.CheckButton(label=label)
            if first is None:
                first = radio
            else:
                radio.set_group(first)
            radio.connect("toggled", self._on_layer, key)
            self._layer_buttons[key] = radio
            self._layer_box.append(radio)
        box.append(self._layer_box)
        box.append(Gtk.Separator())
        self._pin_check = Gtk.CheckButton(label=_("Pin to the top of the list"))
        self._pin_check.set_active(bool(self._note().get("pinned")))
        self._pin_check.connect("toggled", lambda b: self._set_pinned(b.get_active()))
        box.append(self._pin_check)
        lock_btn = Gtk.Button(label=_("Lock note"))
        lock_btn.add_css_class("flat")
        lock_btn.connect("clicked", lambda _b: (self._popover.popdown(),
                                                self.app.set_note_locked(self.note_id, True)))
        box.append(lock_btn)
        show_all = Gtk.Button(label=_("Show all notes"))
        show_all.add_css_class("flat")
        show_all.set_action_name("app.show-all")
        show_all.connect("clicked", lambda _b: self._popover.popdown())
        box.append(show_all)
        delete = Gtk.Button(label=_("Delete note"))
        delete.add_css_class("destructive-action")
        delete.connect("clicked", self._on_delete)
        box.append(delete)

        self._popover = Gtk.Popover(child=box)
        return Gtk.MenuButton(icon_name="view-more-symbolic", popover=self._popover,
                              tooltip_text=_("Color and options"))

    # ---- katman (üstte / altta) ----
    def _on_layer(self, radio, key):
        if not radio.get_active() or self._layer_init:
            return
        self.store.update(self.note_id, touch=False, notify=False, layer=key)
        winpos.set_layer(self, key)

    def _apply_layer(self):
        layer = self._note().get("layer", "normal")
        supported = winpos.supported(self)
        self._layer_init = True
        self._layer_buttons.get(layer, self._layer_buttons["normal"]).set_active(True)
        self._layer_init = False
        self._layer_box.set_sensitive(supported)
        if not supported:
            self._layer_box.set_tooltip_text(_("This feature only works in X11/XWayland mode"))
        elif layer != "normal":
            winpos.set_layer(self, layer)

    # ---- alarm ----
    def _build_alarm(self):
        self.calendar = Gtk.Calendar()
        self.hour = Gtk.SpinButton.new_with_range(0, 23, 1)
        self.minute = Gtk.SpinButton.new_with_range(0, 59, 1)
        for spin in (self.hour, self.minute):
            spin.set_wrap(True)
            spin.set_width_chars(2)
            spin.connect("output", lambda s: (s.set_text(f"{int(s.get_value()):02d}"), True)[1])
        time_row = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        for widget in (self.hour, Gtk.Label(label=":"), self.minute):
            time_row.append(widget)

        self.repeat = Gtk.DropDown.new_from_strings([_("Once"), _("Every day"), _("Every week")])
        repeat_row = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        repeat_row.append(Gtk.Label(label=_("Repeat:")))
        repeat_row.append(self.repeat)

        self.alarm_msg = Gtk.Label(css_classes=["error"], visible=False)
        clear = Gtk.Button(label=_("Remove alarm"))
        clear.connect("clicked", self._on_alarm_clear)
        set_btn = Gtk.Button(label=_("Set alarm"))
        set_btn.add_css_class("suggested-action")
        set_btn.connect("clicked", self._on_alarm_set)
        buttons = Gtk.Box(spacing=6, homogeneous=True)
        buttons.append(clear)
        buttons.append(set_btn)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=8,
                      margin_bottom=8, margin_start=8, margin_end=8)
        for widget in (self.calendar, time_row, repeat_row, self.alarm_msg, buttons):
            box.append(widget)
        self._alarm_popover = Gtk.Popover(child=box)
        self._alarm_popover.connect("show", self._on_alarm_popover_show)
        self._alarm_label = Gtk.Label(label="⏰")
        self.alarm_btn = Gtk.MenuButton(child=self._alarm_label, popover=self._alarm_popover,
                                        tooltip_text=_("Set alarm"))
        return self.alarm_btn

    def _note(self):
        return self.store.notes.get(self.note_id, {})

    def _alarm_time(self):
        """Gösterilecek en yakın zaman: alarm ya da ertelenmiş alarm."""
        return next_alarm_time(self._note())

    def _on_alarm_popover_show(self, _popover):
        note = self._note()
        ts = note.get("alarm") or (time.time() + 3600)
        dt = GLib.DateTime.new_from_unix_local(int(ts))
        self.calendar.set_date(dt)
        self.hour.set_value(dt.get_hour())
        self.minute.set_value(dt.get_minute() if note.get("alarm") else 0)
        self.repeat.set_selected({"daily": 1, "weekly": 2}.get(note.get("alarm_repeat"), 0))
        self.alarm_msg.set_visible(False)

    def _on_alarm_set(self, _btn):
        day = self.calendar.get_date()
        when = GLib.DateTime.new_local(day.get_year(), day.get_month(), day.get_day_of_month(),
                                       int(self.hour.get_value()), int(self.minute.get_value()), 0)
        ts = when.to_unix()
        if ts <= time.time():
            self.alarm_msg.set_label(_("That time is in the past"))
            self.alarm_msg.set_visible(True)
            return
        repeat = (None, "daily", "weekly")[self.repeat.get_selected()]
        self.store.update(self.note_id, touch=False, notify=True, alarm=ts, alarm_repeat=repeat, snooze=None)
        self._alarm_popover.popdown()
        self.refresh_alarm()

    def _on_alarm_clear(self, _btn):
        self.store.update(self.note_id, touch=False, notify=True, alarm=None, alarm_repeat=None, snooze=None)
        self._alarm_popover.popdown()
        self.refresh_alarm()

    def refresh_alarm(self):
        ts = self._alarm_time()
        if ts:
            dt = GLib.DateTime.new_from_unix_local(int(ts))
            today = GLib.DateTime.new_now_local()
            same_day = dt.format("%Y%m%d") == today.format("%Y%m%d")
            when = dt.format("%H:%M" if same_day else "%d.%m %H:%M")
            repeat = {"daily": _(" ↻ every day"), "weekly": _(" ↻ every week")}.get(self._note().get("alarm_repeat"), "")
            self._alarm_label.set_label(f"⏰ {when}{' ↻' if repeat else ''}")
            self._lock_alarm.set_label(f"⏰ {when}{' ↻' if repeat else ''}")
            self._lock_alarm.set_visible(True)
            snoozed = self._note().get("snooze")
            self.alarm_btn.set_tooltip_text(
                (_("Snoozed: ") if snoozed else _("Alarm: ")) + dt.format("%d.%m.%Y %H:%M") + repeat)
            self.alarm_btn.add_css_class("alarm-set")      # kurulu alarm koyu hap olarak görünür
        else:
            self._alarm_label.set_label("⏰")
            self._lock_alarm.set_visible(False)
            self.alarm_btn.set_tooltip_text(_("Set alarm"))
            self.alarm_btn.remove_css_class("alarm-set")
        self._update_chrome()

    def _build_actions(self):
        action = Gio.SimpleAction.new("format", GLib.VariantType("s"))
        action.connect("activate", lambda _a, param: self.toggle_format(param.get_string()))
        self.add_action(action)
        list_action = Gio.SimpleAction.new("list", GLib.VariantType("s"))
        list_action.connect("activate", lambda _a, param: self.toggle_list(param.get_string()))
        self.add_action(list_action)
        lock_action = Gio.SimpleAction.new("toggle-lock", None)
        lock_action.connect("activate", lambda *_: self.app.set_note_locked(self.note_id, not self._locked))
        self.add_action(lock_action)
        self._pin_action = Gio.SimpleAction.new_stateful(
            "pin", None, GLib.Variant("b", bool(self._note().get("pinned"))))
        self._pin_action.connect("change-state", lambda _a, value: self._set_pinned(value.get_boolean()))
        self.add_action(self._pin_action)
        delete_action = Gio.SimpleAction.new("delete", None)
        delete_action.connect("activate", lambda *_: self._on_delete(None))
        self.add_action(delete_action)
        color_action = Gio.SimpleAction.new("color", GLib.VariantType("s"))
        color_action.connect("activate", lambda _a, param: self.set_color(param.get_string()))
        self.add_action(color_action)
        zoom_action = Gio.SimpleAction.new("zoom", GLib.VariantType("s"))
        zoom_action.connect("activate", lambda _a, param: self.change_font_size(
            1 if param.get_string() == "in" else -1))
        self.add_action(zoom_action)

    # ---- kilit ----
    def set_locked(self, locked):
        """Kilitler/açar. Notun o anki hali (açık ya da yalnız başlık) olduğu gibi kalır."""
        locked = bool(locked)
        if locked == self._locked:
            return
        if locked:
            # Kilitlenince pencere şimdiki boyutunda sabitlenir (boyutlandırılamaz hale gelirken kaymasın)
            width = self.get_width() or self._expanded_width
            height = 1 if self._collapsed else (self.get_height() or self._expanded_height)
            self.set_default_size(width, height)
        self._locked = locked
        self.store.update(self.note_id, touch=False, notify=True, locked=locked)
        self._apply_lock()

    def _apply_lock(self):
        locked = self._locked
        in_top = self._header.get_parent() is self._top
        if locked and in_top:
            # Şerit, başlık çubuğuyla aynı yükseklikte olsun: kilitlenince pencere boyutu kaymasın
            header_height = self._header.get_height()
            self._lock_strip.set_size_request(-1, header_height if header_height > 0 else 40)
            self._top.remove(self._header)
            self._top.prepend(self._lock_strip)
        elif not locked and self._lock_strip.get_parent() is self._top:
            self._top.remove(self._lock_strip)
            self._top.prepend(self._header)
        self.textview.set_editable(not locked)
        self.textview.set_cursor_visible(not locked)
        self.set_resizable(not locked)
        if locked:
            self.add_css_class("locked")
        else:
            self.remove_css_class("locked")
        # Düzenleme/silme/biçim eylemleri kapanır; sabitleme, yeni not ve tüm notlar açık kalır
        for name in ("delete", "color", "format", "list", "zoom"):
            action = self.lookup_action(name)
            if action is not None:
                action.set_enabled(not locked)
        self._lock_section.remove_all()
        self._lock_section.append(_("Unlock note") if locked else _("Lock note"), "win.toggle-lock")
        if self.get_mapped():
            winpos.set_functions(self, not locked)
        self._update_title()
        self.refresh_alarm()
        self._update_chrome()

    def _set_pinned(self, pinned):
        """Sabitleme durumunu kaydeder; menü onay kutusu ve sağ tık öğesi eşit kalır."""
        pinned = bool(pinned)
        self.store.update(self.note_id, touch=False, notify=True, pinned=pinned)
        if self._pin_check.get_active() != pinned:
            self._pin_check.set_active(pinned)
        self._pin_action.set_state(GLib.Variant("b", pinned))

    # ---- yazı boyutu ----
    def set_font_size(self, size, save=True):
        if size not in FONT_SIZES:
            size = DEFAULT_FONT_SIZE
        if self.font_size:
            self.remove_css_class(f"fs-{self.font_size}")
        self.font_size = size
        self.add_css_class(f"fs-{size}")
        if save:
            self.store.update(self.note_id, touch=False, font_size=size)

    def _size_at(self, it):
        """İmleçteki karakterin boyutu (px); boyut etiketi yoksa notun taban boyutu."""
        for name, px in SIZE_TAGS.items():
            if it.has_tag(self._tag(name)):
                return px
        return self.font_size

    def _step_size(self, px, step):
        idx = FONT_SIZES.index(px) if px in FONT_SIZES else FONT_SIZES.index(DEFAULT_FONT_SIZE)
        return FONT_SIZES[max(0, min(idx + step, len(FONT_SIZES) - 1))]

    def change_font_size(self, step):
        """Seçili metni büyütür/küçültür; seçim yoksa bundan sonra yazılan metni."""
        buf = self.buffer
        bounds = buf.get_selection_bounds()
        if not bounds:
            it = buf.get_iter_at_mark(buf.get_insert())
            prev = it.copy()
            if not prev.is_start():
                prev.backward_char()
            current = self._pending.get("size") or self._size_at(prev)
            self._pending["size"] = self._step_size(current, step)
            return
        start, end = bounds
        first, last = start.get_offset(), end.get_offset()
        # Farklı boyutlu parçaları ayrı ayrı bir adım büyüt/küçült
        runs, run_start, run_size = [], first, None
        for off in range(first, last):
            size = self._size_at(buf.get_iter_at_offset(off))
            if run_size is None:
                run_size = size
            elif size != run_size:
                runs.append((run_start, off, run_size))
                run_start, run_size = off, size
        if run_size is not None:
            runs.append((run_start, last, run_size))
        self._begin_edit()
        for a, b, size in runs:
            a_it, b_it = buf.get_iter_at_offset(a), buf.get_iter_at_offset(b)
            for name in SIZE_TAGS:
                buf.remove_tag_by_name(name, a_it, b_it)
            new = self._step_size(size, step)
            buf.apply_tag_by_name(f"size-{new}", buf.get_iter_at_offset(a), buf.get_iter_at_offset(b))
        buf.select_range(buf.get_iter_at_offset(first), buf.get_iter_at_offset(last))
        self._finish_edit()

    # ---- renk / silme ----
    def set_color(self, color, save=True):
        if color not in COLORS:
            color = "yellow"
        if self.color:
            self.remove_css_class(f"note-{self.color}")
        self.color = color
        self.add_css_class(f"note-{color}")
        if save:
            self.store.update(self.note_id, color=color)

    def _on_swatch(self, _btn, name):
        self._popover.popdown()
        self.set_color(name)

    def _on_delete(self, _btn):
        if self._locked:
            return
        self._popover.popdown()
        dialog = Adw.AlertDialog(heading=_("Delete this note?"),
                                 body=_("The note moves to the trash and can be restored within 30 days."))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Move to trash"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, r: r == "delete" and self.app.delete_note(self.note_id))
        dialog.present(self)

    # ---- kayıt ----
    def _text(self):
        return self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), False)

    def _save_from_buffer(self):
        if self._loading or self._suspend_save:
            return
        self.store.update(self.note_id, text=self._text(), tags=serialize_tags(self.buffer))

    def _on_changed(self, _buf):
        self._update_title()
        self._save_from_buffer()

    def _on_tag_changed(self, *_):
        self._save_from_buffer()

    def _update_title(self):
        text = self._text().strip()
        first = text.split("\n", 1)[0] if text else ""
        first = first.lstrip("•☐☑ ")
        title = first[:60] or _("New note")
        self.set_title(title)
        self.title_label.set_label(title)
        self._lock_title.set_label(title)

    # ---- başlığa küçültme ----
    def _on_header_right_click(self, _gesture, _n_press, x, y):
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self._context_popover.set_pointing_to(rect)
        self._context_popover.popup()

    def _on_header_pressed(self, gesture, n_press, x, y, header):
        if n_press != 2:
            return
        widget = header.pick(x, y, Gtk.PickFlags.DEFAULT)
        while widget is not None and widget is not header:
            if isinstance(widget, (Gtk.Button, Gtk.MenuButton)):
                return
            widget = widget.get_parent()
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        if self._show_id:                                # bekleyen "düğmeleri göster" iptal
            GLib.source_remove(self._show_id)
            self._show_id = 0
        self._chrome_on = True
        self.set_collapsed(not self._collapsed)

    def _resize_to(self, width, height, force=False):
        """Açık pencereyi yeniden boyutlandırır.

        X11'de set_default_size açık pencereyi büyütmez, set_size_request ise küçültmez; bu yüzden
        ikisi birlikte kullanılır. Asgari boyut, kullanıcı notu elle küçültebilsin diye kısa süre
        sonra eski değerine döndürülür. GTK X11'de küçültülmüş pencerenin boyutunu hâlâ eski sandığı
        için "aynı boyutu iste" komutunu yok sayabilir; force=True bu durumda present() ile yeniden
        yerleşimi zorlar (yalnızca kullanıcı eylemlerinde, çünkü pencereyi öne getirir).
        """
        width, height = max(1, int(width)), max(1, int(height))
        self.set_size_request(width, height)
        self.set_default_size(width, height)
        if force and self.get_mapped():
            self.present()
        if self._min_id:
            GLib.source_remove(self._min_id)
        self._min_id = GLib.timeout_add(350, self._reset_min_size)

    def _reset_min_size(self):
        self._min_id = 0
        self.set_size_request(*MIN_SIZE)
        return GLib.SOURCE_REMOVE

    # ---- pencere kromu (düğmeler) ----
    def _chrome_wanted(self):
        """Düğmeler, nota tıklandıktan sonra odak başka yere geçene kadar görünür."""
        return ((self._chrome_on and self.is_active()) or self._popover.get_visible()
                or self._alarm_popover.get_visible() or self.get_visible_dialog() is not None)

    def _on_press(self, gesture, n_press=1, x=0, y=0):
        """Nota her basışta çalışır. Basış anında düğmeleri yeniden yerleştirmez: düğme basış ile
        bırakma arasında yer değiştirirse tıklama kaybolur ve çift tıklamanın ikinci basışı başka bir
        düğmeye denk gelir."""
        if self._locked:
            self.stop_ring(update=False)
            # Sağ tık (kilidi açma menüsü) dışında her basış yutulur: kilitli not dokunulmazdır
            if gesture is not None and gesture.get_current_button() != Gdk.BUTTON_SECONDARY:
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            return
        if time.monotonic() - self._last_toggle < TOGGLE_GUARD:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)   # çoklu tıklamanın artan basışlarını yut
            return
        in_header = on_button = False
        widget = self._view.pick(x, y, Gtk.PickFlags.DEFAULT)
        while widget is not None:
            if widget is self._snooze_btn:
                return                                   # erteleme düğmesi alarmı susturmasın
            if isinstance(widget, (Gtk.Button, Gtk.MenuButton)):
                on_button = True
            if widget is self._header:
                in_header = True
            widget = widget.get_parent()
        self.stop_ring(update=False)
        if on_button:
            self._chrome_on = True                       # sessizce: düzeni değiştirmeden düğmeler açık kalsın
            return
        if self._chrome_on:
            return
        if in_header:
            # Başlığa basış çift tıklamanın ilki olabilir; düzeni değiştirmeden biraz bekle
            if n_press == 1 and not self._show_id:
                self._show_id = GLib.timeout_add(350, self._show_chrome_now)
            return
        self._show_chrome_now()

    def _show_chrome_now(self):
        self._show_id = 0
        self._chrome_on = True
        self._update_chrome()
        return GLib.SOURCE_REMOVE

    def _schedule_chrome(self, *_):
        # Menü/uyarı açılırken pencere kısa süre etkin olmayabilir; hemen karar verme
        if not self._chrome_id:
            self._chrome_id = GLib.timeout_add(250, self._chrome_tick)

    def _close_popovers(self):
        for popover in (self._popover, self._alarm_popover, self._context_popover):
            if popover.get_visible():
                popover.popdown()

    def _chrome_tick(self):
        self._chrome_id = 0
        if not self.is_active():
            # X11 (XWayland) altında açık menü, odak başka uygulamaya geçince kapanmaz ve düğmeleri
            # görünür tutar; odak gidince menüleri biz kapatırız.
            self._close_popovers()
        if not self.is_active() and not self._chrome_wanted():
            self._chrome_on = False      # odak başka pencereye/uygulamaya geçti: sade görünüme dön
        self._update_chrome()
        return GLib.SOURCE_REMOVE

    def _update_chrome(self):
        if self._locked:
            self._bar.set_visible(False)             # kilitliyken hiç düğme/araç çubuğu yok
            return
        show = self._chrome_wanted() or self._ringing
        full = show and not self._collapsed        # tüm düğmeler
        has_alarm = bool(self._alarm_time())
        self._header.set_show_end_title_buttons(full)
        self._new_btn.set_visible(full)
        self._collapse_btn.set_visible(full)
        self._menu_btn.set_visible(show)
        self._snooze_btn.set_visible(self._ringing)
        self.alarm_btn.set_visible(show or has_alarm)   # kurulu alarm saati hep görünür
        self._bar.set_visible(full)
        # Sol taraf boşken başlık pencerenin tam ortasında kalsın
        self._header.set_centering_policy(
            Adw.CenteringPolicy.LOOSE if full else Adw.CenteringPolicy.STRICT)

    # ---- alarm çalarken sallanma ----
    def ring(self):
        """Alarm çalınca not penceresini sallar; nota tıklayınca durur."""
        self._ringing = True
        self._ring_ticks = 0
        note = self.store.notes.get(self.note_id, {})
        base_w = self.get_width() or note.get("width", 320)      # pencere henüz boyutlanmadıysa kayıtlıyı kullan
        base_h = self.get_height() or note.get("height", 360)
        self._ring_base = (base_w, 1 if self._collapsed else base_h)
        self._update_chrome()
        if not self._ring_id:
            self._ring_id = GLib.timeout_add(45, self._ring_tick)

    def _ring_tick(self):
        self._ring_ticks += 1
        for cls in ("shake-a", "shake-b"):
            self._view.remove_css_class(cls)
        self.remove_css_class("ring-flash")
        base_w, base_h = self._ring_base
        if self._ring_ticks >= RING_TICKS:
            self.stop_ring()
            return GLib.SOURCE_REMOVE
        if self._pointer_inside:                     # fare notun üstünde: düğmelere basılabilsin diye dur
            self._resize_to(base_w, base_h)
            return GLib.SOURCE_CONTINUE
        if (self._ring_ticks // 14) % 2 == 0:       # ~0,6 sn salla, ~0,6 sn dur
            odd = self._ring_ticks % 2
            self._view.add_css_class("shake-a" if odd else "shake-b")
            self.add_css_class("ring-flash")
            # Pencerenin kendisi de titresin (kenarlar masaüstünde oynar)
            dx, dy = (RING_JITTER, RING_JITTER) if odd else (-RING_JITTER, -RING_JITTER)
            if not self._locked:                     # kilitli notun boyutu oynamaz; yalnız içeriği sallanır
                self._resize_to(base_w + dx, base_h if self._collapsed else base_h + dy)
        elif not self._locked:
            self._resize_to(base_w, base_h)
        return GLib.SOURCE_CONTINUE

    def stop_ring(self, update=True):
        if self._ring_id:
            GLib.source_remove(self._ring_id)
            self._ring_id = 0
        for cls in ("shake-a", "shake-b"):
            self._view.remove_css_class(cls)
        self.remove_css_class("ring-flash")
        if self._ringing:
            if self._ring_base and not self._locked:
                self._resize_to(*self._ring_base)
            self._ringing = False
            sound.stop_alarm()
            if update:
                self._update_chrome()
            else:
                self._schedule_chrome()

    def set_collapsed(self, collapsed, save=True):
        if self._locked and save:
            return                                       # kilitli not küçültülüp büyütülemez
        self._last_toggle = time.monotonic()
        if collapsed and not self._collapsed:
            # Açık boyutu hatırla ki geri büyürken kaymasın
            if self.get_height() > 100:
                self._expanded_height = self.get_height()
            if self.get_width() > 100:
                self._expanded_width = self.get_width()
        self._collapsed = collapsed
        self._scrolled.set_visible(not collapsed)
        self._update_chrome()
        width = (self.get_width() or self._expanded_width) if collapsed else self._expanded_width
        self._resize_to(width, 1 if collapsed else self._expanded_height, force=True)
        if save:
            self.store.update(self.note_id, touch=False, collapsed=collapsed,
                              width=self._expanded_width, height=self._expanded_height)

    def capture_state(self):
        if self._ringing and self._ring_base:      # titreşim ortasında boyutu bozma
            width, height = self._ring_base[0], self._expanded_height
        else:
            width = self._expanded_width if self._collapsed else self.get_width()
            height = self._expanded_height if self._collapsed else self.get_height()
        fields = {"width": width, "height": height, "collapsed": self._collapsed}
        pos = winpos.get_position(self) if self._pos_last is not None else None
        if pos:
            fields["x"], fields["y"] = pos
        self.store.update(self.note_id, touch=False, **fields)

    # ---- konumu hatırlama (X11/XWayland) ----
    def _on_map(self, *_):
        self.textview.grab_focus()
        self._schedule_chrome()
        GLib.timeout_add(250, self._restore_position)

    def _restore_position(self):
        winpos.set_skip_taskbar(self)
        if self._locked:
            winpos.set_functions(self, False)   # notlar dock'ta ayrı uygulama gibi görünmesin
        self._apply_layer()
        note = self.store.notes.get(self.note_id, {})
        if note.get("x") is not None and note.get("y") is not None:
            winpos.set_position(self, note["x"], note["y"])
        GLib.timeout_add(600, self._start_tracking)
        return GLib.SOURCE_REMOVE

    def _start_tracking(self):
        # Geri yüklemeden sonra başla; böylece açılıştaki geçici konum kayıtlı olanın üstüne yazılmaz
        self._pos_last = winpos.get_position(self) or (0, 0)
        GLib.timeout_add(1500, self._track_position)
        return GLib.SOURCE_REMOVE

    def _track_position(self):
        if self._closed:
            return GLib.SOURCE_REMOVE
        pos = winpos.get_position(self)
        if pos and pos != self._pos_last and not self._ringing:
            self._pos_last = pos
            self.store.update(self.note_id, touch=False, notify=False, x=pos[0], y=pos[1])
        return GLib.SOURCE_CONTINUE

    def _on_close(self, *_):
        if self._locked and not self.app.quitting:
            return True                                  # kilitli not kapanamaz (Ctrl+W, Alt+F4 dahil)
        self.stop_ring()
        self.capture_state()
        self._closed = True
        self._context_popover.unparent()
        if not self.app.quitting:
            self.store.update(self.note_id, touch=False, open=False)
        self.store.save_now()
        self.app.note_windows.pop(self.note_id, None)
        return False

    # ---- biçimlendirme ----
    def _tag(self, name):
        return self.buffer.get_tag_table().lookup(name)

    def _prev_char_has(self, it, tag):
        if it.is_start():
            return False
        prev = it.copy()
        prev.backward_char()
        return prev.has_tag(tag)

    def _state(self, name):
        tag = self._tag(name)
        bounds = self.buffer.get_selection_bounds()
        if bounds:
            return bounds[0].has_tag(tag)
        if name in self._pending:
            return self._pending[name]
        return self._prev_char_has(self.buffer.get_iter_at_mark(self.buffer.get_insert()), tag)

    def toggle_format(self, name):
        tag = self._tag(name)
        bounds = self.buffer.get_selection_bounds()
        if bounds:
            start, end = bounds
            all_on = True
            it = start.copy()
            while it.compare(end) < 0:
                if not it.has_tag(tag):
                    all_on = False
                    break
                it.forward_char()
            if all_on:
                self.buffer.remove_tag(tag, start, end)
            else:
                self.buffer.apply_tag(tag, start, end)
        else:
            self._pending[name] = not self._state(name)
        self._sync_buttons()

    def _on_fmt_button(self, btn, name):
        if self._syncing:
            return
        self.toggle_format(name)
        self.textview.grab_focus()

    def _sync_buttons(self):
        self._syncing = True
        for name, btn in self.fmt_buttons.items():
            btn.set_active(self._state(name))
        self._syncing = False

    def _on_key_pressed(self, _ctrl, keyval, _code, state):
        if self._locked:
            return False
        if keyval in NAV_KEYS:
            self._pending.clear()
        if (keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter)
                and not state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
                and not self.buffer.get_has_selection()):
            return self._continue_list()
        return False

    # ---- madde işareti / yapılacaklar ----
    def _line_start(self, n):
        return self.buffer.get_iter_at_line(n)[1]

    def _line_text(self, n):
        start = self._line_start(n)
        end = start.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        return self.buffer.get_text(start, end, False)

    def _insert_plain(self, it, text):
        """Biçim mirası olmadan ekler (madde işareti karakterleri için)."""
        self._plain = True
        self.buffer.insert(it, text)
        self._plain = False

    def _apply_glyph_tags(self):
        """Her liste satırının ilk karakterini (•, ☐, ☑) büyütür."""
        buf = self.buffer
        glyph = self._tag("glyph")
        buf.remove_tag(glyph, buf.get_start_iter(), buf.get_end_iter())
        for n in range(buf.get_line_count()):
            if list_kind(self._line_text(n)):
                start = self._line_start(n)
                end = start.copy()
                end.forward_char()
                buf.apply_tag(glyph, start, end)

    def _finish_edit(self):
        self._apply_glyph_tags()
        self.buffer.end_user_action()
        self._suspend_save = False
        self._save_from_buffer()

    def _begin_edit(self):
        self._suspend_save = True
        self.buffer.begin_user_action()

    def toggle_list(self, kind):
        buf = self.buffer
        bounds = buf.get_selection_bounds()
        if bounds:
            first, last = bounds[0].get_line(), bounds[1].get_line()
            if bounds[1].starts_line() and last > first:
                last -= 1
        else:
            first = last = buf.get_iter_at_mark(buf.get_insert()).get_line()
        lines = range(first, last + 1)
        remove = all(list_kind(self._line_text(n)) == kind for n in lines)
        self._begin_edit()
        for n in reversed(lines):
            start = self._line_start(n)
            if list_kind(self._line_text(n)):
                end = start.copy()
                end.forward_chars(2)
                buf.delete(start, end)
            if not remove:
                self._insert_plain(self._line_start(n), PREFIXES[kind])
            self._set_line_done(n, False)
        self._finish_edit()

    def _continue_list(self):
        buf = self.buffer
        it = buf.get_iter_at_mark(buf.get_insert())
        line = self._line_text(it.get_line())
        kind = list_kind(line)
        if not kind or it.get_line_offset() < 2:
            return False
        self._begin_edit()
        if not line[2:].strip():
            start = self._line_start(it.get_line())
            end = start.copy()
            end.forward_chars(2)
            buf.delete(start, end)
        else:
            self._insert_plain(it, "\n" + PREFIXES[kind])
        self._finish_edit()
        return True

    def _on_click_pressed(self, gesture, n_press, x, y):
        if self._locked:
            return
        # TextView kendi tıklama hareketini sahiplendiği için "released" hiç gelmez;
        # bu yüzden basıldığı anda işliyoruz.
        self._pending.clear()
        if n_press != 1:
            return
        bx, by = self.textview.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        found, it = self.textview.get_iter_at_location(bx, by)
        if found and it.get_line_offset() == 0 and it.get_char() in CHECK_GLYPHS:
            rect = self.textview.get_iter_location(it)
            if rect.x <= bx < rect.x + rect.width and rect.y <= by < rect.y + rect.height:
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                self._toggle_check(it)

    def _set_line_done(self, line, done):
        """☑ satırının metnini üstü çizili yapar, ☐ satırında çizgiyi kaldırır."""
        start = self._line_start(line)
        end = start.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        if done:
            start.forward_chars(2)
            if start.compare(end) < 0:
                self.buffer.apply_tag_by_name("done", start, end)
        else:
            self.buffer.remove_tag_by_name("done", start, end)

    def _toggle_check(self, it):
        buf = self.buffer
        cursor = buf.get_iter_at_mark(buf.get_insert()).get_offset()
        line = it.get_line()
        done = it.get_char() == "☐"
        end = it.copy()
        end.forward_char()
        self._begin_edit()
        buf.delete(it, end)
        self._insert_plain(it, "☑" if done else "☐")
        self._set_line_done(line, done)
        buf.place_cursor(buf.get_iter_at_offset(cursor))
        self._finish_edit()

    def _on_insert_before(self, buf, location, _text, _length):
        self._prev_state = {
            name: self._prev_char_has(location, self._tag(name)) for name in TAGS
        }

    def _on_insert_after(self, buf, location, text, _length):
        if self._loading:
            return
        start = location.copy()
        start.backward_chars(len(text))
        was_suspended = self._suspend_save
        self._suspend_save = True
        pending_size = self._pending.get("size")
        for name in TAGS:
            if name in SIZE_TAGS and pending_size is not None and not self._plain:
                want = SIZE_TAGS[name] == pending_size
            else:
                want = False if self._plain else self._pending.get(name, self._prev_state.get(name, False))
            if want:
                buf.apply_tag_by_name(name, start, location)
            else:
                buf.remove_tag_by_name(name, start, location)
        self._suspend_save = was_suspended
        self._save_from_buffer()
