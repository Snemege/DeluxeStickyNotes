import os

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from . import winpos
from .i18n import _
from .store import APP_ID, next_alarm_time

CARD_W, CARD_H = 200, 160


def fold(text):
    """Türkçe İ/I farkını gözeterek büyük/küçük harf duyarsız karşılaştırma."""
    return text.replace("İ", "i").replace("I", "ı").casefold()


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, store, settings):
        super().__init__(application=app, default_width=settings.get("main_width"),
                         default_height=settings.get("main_height"), title=_("Deluxe Sticky Notes"))
        self.app = app
        self.store = store
        self.settings = settings
        self.connect("map", lambda *_: GLib.timeout_add(250, self._restore_position))
        self.connect("notify::is-active", self._on_active_changed)
        self._rebuild_id = 0

        header = Adw.HeaderBar()
        brand = Gtk.Box(spacing=8)
        brand.append(Gtk.Image(icon_name=APP_ID, pixel_size=22))
        brand.append(Gtk.Label(label=_("Deluxe Sticky Notes"), css_classes=["heading"]))
        header.set_title_widget(brand)
        new_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("New note (Ctrl+N)"))
        new_btn.set_action_name("app.new-note")
        header.pack_start(new_btn)
        menu = Gio.Menu()
        menu.append(_("Trash"), "app.trash")
        menu.append(_("Export all notes…"), "app.export-all")
        menu.append(_("Import notes from a file…"), "app.import-file")
        menu.append(_("Suggest to the developers…"), "app.feedback")
        menu.append(_("Settings"), "app.settings")
        menu.append(_("Quit (Ctrl+Q)"), "app.quit")
        main_menu = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text=_("Menu"))
        self._menu_buttons = [main_menu]
        header.pack_end(main_menu)
        search_btn = Gtk.ToggleButton(icon_name="system-search-symbolic", tooltip_text=_("Search (Ctrl+F)"))
        header.pack_end(search_btn)
        self.connect("close-request", lambda *_: app.handle_main_close(self))

        self.entry = Gtk.SearchEntry(placeholder_text=_("Search notes"), hexpand=True)
        self.search_bar = Gtk.SearchBar(child=self.entry)
        self.search_bar.connect_entry(self.entry)
        self.search_bar.set_key_capture_widget(self)
        search_btn.bind_property("active", self.search_bar, "search-mode-enabled",
                                 GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        self.entry.connect("search-changed", lambda _e: self._rebuild())

        action = Gio.SimpleAction.new("search", None)
        action.connect("activate", lambda *_: search_btn.set_active(True) or self.entry.grab_focus())
        self.add_action(action)

        self.flow = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, valign=Gtk.Align.START,
            min_children_per_line=1, max_children_per_line=8, row_spacing=12, column_spacing=12,
            margin_top=12, margin_bottom=12, margin_start=12, margin_end=12,
        )
        scrolled = Gtk.ScrolledWindow(child=self.flow, vexpand=True)
        self.stack = Gtk.Stack()
        # Kart menüsünün popover'ı FlowBox'a değil bu kutuya bağlanır (FlowBox çocuklarını kendi yönetir)
        self._list_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._list_holder.append(scrolled)
        self.stack.add_named(self._list_holder, "list")
        self.stack.add_named(Adw.StatusPage(
            icon_name=APP_ID, title=_("No notes yet"),
            description=_("Press Ctrl+N to create a new note.")), "empty")
        self.stack.add_named(Adw.StatusPage(
            icon_name="system-search-symbolic", title=_("No results"),
            description=_("No note matches your search.")), "nomatch")

        self.toasts = Adw.ToastOverlay(child=self.stack)
        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        view.add_top_bar(self.search_bar)
        self.set_content(view)

        # Kartlara sağ tık menüsü: tek bir paylaşılan popover, kartlar yenilenince bozulmaz
        self._card_popover = Gtk.PopoverMenu(has_arrow=False)
        self._card_popover.set_parent(self._list_holder)
        for name, callback in (("card-open", self.app.open_note), ("card-pin", self._toggle_pin),
                               ("card-lock", self._toggle_lock), ("card-delete", self.app.delete_note)):
            action = Gio.SimpleAction.new(name, GLib.VariantType("s"))
            action.connect("activate", lambda _a, param, cb=callback: cb(param.get_string()))
            self.add_action(action)

        store.connect(self._schedule_rebuild)
        self._rebuild()
        if store.migrated_from:
            self.toasts.add_toast(Adw.Toast(title=_("Your notes were moved over from the previous version.")))
        if store.recovered_from:
            self.toasts.add_toast(Adw.Toast(
                title=_("Notes were restored from a backup because the file was corrupt ({date})").format(
                    date=store.recovered_from[6:-5]),
                timeout=0))

    def _on_active_changed(self, *_):
        if not self.is_active():
            GLib.timeout_add(250, self._close_menus)

    def _close_menus(self):
        """Odak başka uygulamaya geçince X11'de açık menüler kapanmaz; biz kapatırız."""
        if not self.is_active():
            self._card_popover.popdown()
            for button in self._menu_buttons:
                button.popdown()
        return GLib.SOURCE_REMOVE

    def _toggle_lock(self, note_id):
        note = self.store.notes.get(note_id)
        if note is not None:
            self.app.set_note_locked(note_id, not note.get("locked"))

    def _toggle_pin(self, note_id):
        note = self.store.notes.get(note_id)
        if note is not None:
            self.store.update(note_id, touch=False, notify=True, pinned=not note.get("pinned"))

    def _on_card_right_click(self, _gesture, _n_press, x, y, note_id, card):
        note = self.store.notes.get(note_id)
        if note is None:
            return
        menu = Gio.Menu()
        menu.append(_("Edit"), f"win.card-open::{note_id}")
        menu.append(_("Unpin") if note.get("pinned") else _("Pin"), f"win.card-pin::{note_id}")
        menu.append(_("Unlock note") if note.get("locked") else _("Lock note"), f"win.card-lock::{note_id}")
        if not note.get("locked"):
            menu.append(_("Delete"), f"win.card-delete::{note_id}")   # kilitli not silinemez
        self._card_popover.set_menu_model(menu)
        point = card.translate_coordinates(self._list_holder, x, y)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = (int(point[0]), int(point[1]), 1, 1) if point else (0, 0, 1, 1)
        self._card_popover.set_pointing_to(rect)
        self._card_popover.popup()

    def release(self):
        """Pencere yok edilmeden önce çağrılır: flow'a bağlı popover ayrılmalı."""
        self._card_popover.unparent()

    def _restore_position(self):
        x, y = self.settings.get("main_x"), self.settings.get("main_y")
        if x is not None and y is not None:
            winpos.set_position(self, x, y)
        return GLib.SOURCE_REMOVE

    def save_geometry(self):
        if self.get_width() > 100:
            self.settings.set("main_width", self.get_width())
            self.settings.set("main_height", self.get_height())
        pos = winpos.get_position(self)
        if pos:
            self.settings.set("main_x", pos[0])
            self.settings.set("main_y", pos[1])

    def _schedule_rebuild(self):
        if not self._rebuild_id:
            self._rebuild_id = GLib.timeout_add(250, self._rebuild)

    def _rebuild(self):
        if self._rebuild_id:
            GLib.source_remove(self._rebuild_id)
        self._rebuild_id = 0
        self.flow.remove_all()          # yalnızca kartlar; flow'a bağlı popover'a dokunmaz
        query = fold(self.entry.get_text().strip())
        all_notes = self.store.sorted_notes()
        notes = [n for n in all_notes if query in fold(n["text"])] if query else all_notes
        for note in notes:
            self.flow.append(self._make_card(note))
        if not all_notes:
            self.stack.set_visible_child_name("empty")
        elif not notes:
            self.stack.set_visible_child_name("nomatch")
        else:
            self.stack.set_visible_child_name("list")
        return GLib.SOURCE_REMOVE

    def _make_card(self, note):
        text = note["text"].strip()
        label = Gtk.Label(
            label=text or _("Empty note"), xalign=0, yalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
            ellipsize=Pango.EllipsizeMode.END, lines=7, opacity=1.0 if text else 0.5,
        )
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        label.set_vexpand(True)
        content.append(label)
        when_ts = next_alarm_time(note)
        if when_ts:
            when = GLib.DateTime.new_from_unix_local(int(when_ts)).format("%d.%m %H:%M")
            repeat = " ↻" if note.get("alarm_repeat") else ""
            content.append(Gtk.Label(label=f"⏰ {when}{repeat}", halign=Gtk.Align.START,
                                     css_classes=["alarm-pill"]))
        if note.get("pinned"):
            label.set_label("📌 " + label.get_label())
        if note.get("locked"):
            label.set_label("🔒 " + label.get_label())
        card = Gtk.Button(child=content, width_request=CARD_W, height_request=CARD_H)
        card.add_css_class("note-card")
        card.add_css_class(f"note-{note['color']}")
        card.connect("clicked", lambda _b, nid=note["id"]: self.app.open_note(nid))
        right = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right.connect("pressed", self._on_card_right_click, note["id"], card)
        card.add_controller(right)
        card.set_tooltip_text(_("Right-click: edit, pin, delete"))
        return card

    def show_deleted_toast(self, note):
        toast = Adw.Toast(title=_("Note deleted"), button_label=_("Undo"), timeout=6)
        toast.connect("button-clicked", lambda _t: self.store.restore(note))
        self.toasts.add_toast(toast)
