from gi.repository import Adw, GLib, Gtk

from .export import note_title
from .i18n import _, ngettext


class TrashDialog(Adw.Dialog):
    """Silinen notlar: geri yükle, kalıcı sil ya da çöpü boşalt."""

    def __init__(self, store):
        super().__init__(title=_("Trash"), content_width=420, content_height=480)
        self.store = store

        self.empty_btn = Gtk.Button(label=_("Empty"), css_classes=["destructive-action"])
        self.empty_btn.connect("clicked", self._on_empty)
        header = Adw.HeaderBar()
        header.pack_start(self.empty_btn)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"],
                                   margin_top=12, margin_bottom=12, margin_start=12, margin_end=12,
                                   valign=Gtk.Align.START)
        scrolled = Gtk.ScrolledWindow(child=self.listbox, vexpand=True)
        self.stack = Gtk.Stack()
        self.stack.add_named(scrolled, "list")
        self.stack.add_named(Adw.StatusPage(
            icon_name="user-trash-symbolic", title=_("Trash is empty"),
            description=_("Deleted notes stay here for 30 days.")), "empty")

        view = Adw.ToolbarView(content=self.stack)
        view.add_top_bar(header)
        self.set_child(view)

        self._listener = self._refresh
        store.connect(self._listener)
        self.connect("closed", lambda *_: store._listeners.remove(self._listener)
                     if self._listener in store._listeners else None)
        self._refresh()

    def _refresh(self):
        while (row := self.listbox.get_first_child()) is not None:
            self.listbox.remove(row)
        notes = sorted(self.store.trash.values(), key=lambda n: n.get("deleted", 0), reverse=True)
        for note in notes:
            when = GLib.DateTime.new_from_unix_local(int(note.get("deleted", 0))).format("%d.%m %H:%M")
            days = self.store.trash_days_left(note)
            row = Adw.ActionRow(title=GLib.markup_escape_text(note_title(note)),
                                subtitle=ngettext(
                                    "Deleted {when} · permanently removed in {n} day",
                                    "Deleted {when} · permanently removed in {n} days", days).format(when=when, n=days))
            restore = Gtk.Button(label=_("Restore"), valign=Gtk.Align.CENTER)
            restore.connect("clicked", lambda _b, i=note["id"]: self.store.trash_restore(i))
            forever = Gtk.Button(icon_name="edit-delete-symbolic", valign=Gtk.Align.CENTER,
                                 tooltip_text=_("Delete permanently"), css_classes=["flat"])
            forever.connect("clicked", lambda _b, i=note["id"]: self.store.trash_delete(i))
            row.add_suffix(restore)
            row.add_suffix(forever)
            self.listbox.append(row)
        self.stack.set_visible_child_name("list" if notes else "empty")
        self.empty_btn.set_sensitive(bool(notes))

    def _on_empty(self, _btn):
        dialog = Adw.AlertDialog(heading=_("Empty the trash?"),
                                 body=_("All notes in the trash will be permanently deleted. This can't be undone."))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("empty", _("Empty"))
        dialog.set_response_appearance("empty", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, r: r == "empty" and self.store.trash_empty())
        dialog.present(self)
