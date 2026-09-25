import os
import time

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import background, export, sound
from .i18n import _, ngettext
from .feedback import FeedbackDialog
from .main_window import MainWindow
from .note_window import NoteWindow
from .settings_dialog import SettingsDialog
from .shortcuts import GlobalShortcuts
from .store import APP_ID, SNOOZE_MINUTES, NoteStore, Settings, advance_alarm
from .trash_dialog import TrashDialog
from .style import load_css
from .tray import Tray

ALARM_CHECK_SECONDS = 15


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.add_main_option("background", ord("b"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             _("Start in the background without opening the main window"), None)
        self.add_main_option("show-all", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             _("Show all notes (sent to the running app)"), None)
        self.add_main_option("new-note", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             _("Create a new note (sent to the running app)"), None)
        self.pending_action = None
        self.connect("handle-local-options", self._on_local_options)
        self.store = None
        self.settings = None
        self.main = None
        self.note_windows = {}
        self.quitting = False
        self.background_start = False
        self.tray = None
        self.shortcuts = None
        self._held = False
        self._started = False
        self._force_close_main = False

    def _on_local_options(self, _app, options):
        if options.contains("background"):
            self.background_start = True
        for action in ("show-all", "new-note"):
            if options.contains(action):
                self.register(None)
                if self.get_is_remote():
                    # Zaten çalışan (arka plandaki) uygulamaya ilet ve çık
                    self.activate_action(action, None)
                    return 0
                self.pending_action = action
        return -1

    def do_startup(self):
        Adw.Application.do_startup(self)
        load_css()
        # Geliştirme sırasında (sisteme kurulmadan) ikon proje klasöründen bulunur
        icons = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "icons")
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(icons)
        Gtk.Window.set_default_icon_name(APP_ID)
        self.store = NoteStore()
        self.settings = Settings(self.store.dir)
        if self.store.migrated_from:
            background.migrate_legacy_autostart(bool(self.settings.get("autostart")))
        if self.settings.get("background"):
            self.hold()
            self._held = True

        for name, callback, accels in [
            ("new-note", lambda *_: self.new_note(), ["<Ctrl>n"]),
            ("show-all", lambda *_: self.show_main(), ["<Ctrl><Shift>a"]),
            ("settings", lambda *_: self.show_settings(), []),
            ("trash", lambda *_: self.show_trash(), []),
            ("export-all", lambda *_: self.export_all(), []),
            ("feedback", lambda *_: self.show_feedback(), []),
            ("import-file", lambda *_: self.import_notes_file(), []),
            ("quit", lambda *_: self.quit_app(), ["<Ctrl>q"]),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
            self.set_accels_for_action(f"app.{name}", accels)
        snooze_action = Gio.SimpleAction.new("snooze", GLib.VariantType("s"))
        snooze_action.connect("activate", lambda _a, param: self.snooze_note(param.get_string()))
        self.add_action(snooze_action)
        open_action = Gio.SimpleAction.new("open-note", GLib.VariantType("s"))
        open_action.connect("activate", lambda _a, param: self.open_note(param.get_string()))
        self.add_action(open_action)

        self.set_accels_for_action("window.close", ["<Ctrl>w"])
        self.set_accels_for_action("win.format::bold", ["<Ctrl>b"])
        self.set_accels_for_action("win.format::italic", ["<Ctrl>i"])
        self.set_accels_for_action("win.format::underline", ["<Ctrl>u"])
        self.set_accels_for_action("win.format::strikethrough", ["<Ctrl><Shift>x"])
        self.set_accels_for_action("win.list::bullet", ["<Ctrl><Shift>l"])
        self.set_accels_for_action("win.list::check", ["<Ctrl><Shift>k"])
        self.set_accels_for_action("win.search", ["<Ctrl>f"])
        self.set_accels_for_action("win.zoom::in", ["<Ctrl>plus", "<Ctrl>equal", "<Ctrl>KP_Add"])
        self.set_accels_for_action("win.zoom::out", ["<Ctrl>minus", "<Ctrl>KP_Subtract"])

        GLib.timeout_add_seconds(ALARM_CHECK_SECONDS, self._check_alarms)
        self.tray = Tray(self)
        self.tray.start()
        self.shortcuts = GlobalShortcuts(self)
        if self.settings.get("global_shortcuts"):
            self.shortcuts.start()

    def do_activate(self):
        first = not self._started
        if first:
            self._started = True
            for note in self.store.sorted_notes():
                if note.get("open"):
                    self.open_note(note["id"])
            self._check_alarms()
        # Otomatik başlatmada (--background) ana pencere açılmaz; kullanıcı açıkça isterse açılır.
        # Hiç pencere olmasa da uygulama kapanmasın diye tutuyoruz (ayara yazılmaz).
        if first and self.background_start:
            if not self._held:
                self.hold()
                self._held = True
        elif first and self.pending_action == "new-note":
            self.new_note()
        else:
            self.show_main()

    def do_shutdown(self):
        self.quitting = True
        for win in list(self.note_windows.values()):
            win.capture_state()
        if self.main is not None:
            self.main.save_geometry()
        if self.store:
            self.store.save_now()
        Adw.Application.do_shutdown(self)

    def quit_app(self):
        self.quitting = True
        self.quit()

    # ---- ana pencere ----
    def show_main(self):
        if self.main is None:
            self.main = MainWindow(self, self.store, self.settings)
        self.main.present()

    def handle_main_close(self, win):
        """Ana pencere kapatılırken çağrılır; True dönerse pencere yok edilmez."""
        win.save_geometry()
        if self.quitting or self._force_close_main:
            if win is self.main:
                win.release()
                self.main = None  # pencere yok edilecek; bir sonraki show_main yenisini oluşturur
            return False
        if self.settings.get("background"):
            win.set_visible(False)
            return True
        self._ask_background(win)
        return True

    def _ask_background(self, win):
        dialog = Adw.AlertDialog(
            heading=_("Keep running in the background?"),
            body=_("If the app keeps running in the background, alarms ring on time and your open notes "
                   "stay where they are. You can reach all notes from the Deluxe Sticky Notes icon in the top "
                   "bar or from a note's right-click menu."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("close", _("No, quit"))
        dialog.add_response("background", _("Yes, keep running"))
        dialog.set_response_appearance("background", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("background")
        dialog.set_close_response("cancel")

        def close_main():
            self._force_close_main = True
            win.close()
            self._force_close_main = False
            return GLib.SOURCE_REMOVE

        def on_response(_dialog, response):
            if response == "background":
                self.set_background(True)
                win.set_visible(False)
                self._notify_background()
            elif response == "close":
                # Uyarı penceresi açıkken ana pencere kapanmaz; kapanmasını bekleyip kapat.
                GLib.timeout_add(200, close_main)

        dialog.connect("response", on_response)
        dialog.present(win)

    def _notify_background(self):
        note = Gio.Notification.new(_("Deluxe Sticky Notes is running in the background"))
        note.set_body(_("Click here to see all notes, or use the Deluxe Sticky Notes icon in the top bar."))
        note.set_icon(Gio.ThemedIcon.new(APP_ID))
        note.set_default_action("app.show-all")
        self.send_notification("background-info", note)

    def show_feedback(self):
        if self.main is not None:
            FeedbackDialog(self.settings).present(self.main)

    def show_trash(self):
        if self.main is not None:
            TrashDialog(self.store).present(self.main)

    def import_notes_file(self):
        """Başka bir notes.json'daki (örn. eski kurulum ya da yedek) notları içe aktarır."""
        if self.main is None:
            return
        dialog = Gtk.FileDialog(title=_("Choose a notes.json file to import"))

        def done(dlg, result):
            try:
                path = dlg.open_finish(result).get_path()
            except GLib.Error:
                return                      # kullanıcı vazgeçti
            try:
                count = self.store.import_from(path)
                title = (ngettext("{n} note imported", "{n} notes imported", count).format(n=count) if count
                         else _("No new notes found (you already have them all)"))
            except ValueError:
                title = _("Couldn't read that file")
            if self.main is not None:
                self.main.toasts.add_toast(Adw.Toast(title=title))

        dialog.open(self.main, None, done)

    def export_all(self):
        """Tüm notları seçilen klasöre Markdown dosyaları olarak yazar."""
        if self.main is None:
            return
        dialog = Gtk.FileDialog(title=_("Folder to save the notes in"))

        def done(dlg, result):
            try:
                folder = dlg.select_folder_finish(result)
            except GLib.Error:
                return                      # kullanıcı vazgeçti
            count = export.export_all(list(self.store.notes.values()), folder.get_path())
            if self.main is not None:
                self.main.toasts.add_toast(Adw.Toast(title=ngettext("{n} note exported", "{n} notes exported", count).format(n=count)))

        dialog.select_folder(self.main, None, done)

    def show_settings(self):
        if self.main is not None:
            SettingsDialog(self).present(self.main)

    # ---- arka plan / otomatik başlatma ----
    def set_background(self, enabled):
        self.settings.set("background", enabled)
        if enabled and not self._held:
            self.hold()
            self._held = True
        elif not enabled and self._held:
            self.release()
            self._held = False

    def set_global_shortcuts(self, enabled):
        self.settings.set("global_shortcuts", enabled)
        if enabled:
            self.shortcuts.start()
        else:
            self.shortcuts.stop()

    def set_autostart(self, enabled):
        ok = background.set_autostart(enabled)
        if ok:
            self.settings.set("autostart", enabled)
        return ok

    # ---- notlar ----
    def open_note(self, note_id):
        if note_id not in self.store.notes:
            return
        win = self.note_windows.get(note_id)
        if win is None:
            win = NoteWindow(self, self.store, note_id)
            self.note_windows[note_id] = win
            self.store.update(note_id, touch=False, open=True)
        win.present()

    def new_note(self):
        note = self.store.create()
        self.open_note(note["id"])

    def set_note_locked(self, note_id, locked):
        """Notu kilitler/açar; not penceresi açıksa hemen uygulanır."""
        if note_id not in self.store.notes:
            return
        win = self.note_windows.get(note_id)
        if win is not None:
            win.set_locked(locked)
        else:
            self.store.update(note_id, touch=False, notify=True, locked=bool(locked))

    def delete_note(self, note_id):
        note = self.store.notes.get(note_id)
        if note is not None and note.get("locked"):
            if self.main is not None and self.main.is_visible():
                self.main.toasts.add_toast(Adw.Toast(title=_("Unlock the note first")))
            return                                   # kilitli not silinemez
        win = self.note_windows.pop(note_id, None)
        note = self.store.delete(note_id)
        self.withdraw_notification(f"alarm-{note_id}")
        if win:
            win.close()
        if note and self.main is not None and self.main.is_visible():
            self.main.show_deleted_toast(note)

    # ---- alarmlar ----
    def _check_alarms(self):
        now = time.time()
        for note in list(self.store.notes.values()):
            alarm, snooze = note.get("alarm"), note.get("snooze")
            if alarm and alarm <= now:
                self._fire_alarm(note, missed=now - alarm > 2 * ALARM_CHECK_SECONDS)
            elif snooze and snooze <= now:
                self._fire_alarm(note, missed=now - snooze > 2 * ALARM_CHECK_SECONDS, snoozed=True)
        return GLib.SOURCE_CONTINUE

    def snooze_note(self, note_id, minutes=SNOOZE_MINUTES):
        """Alarmı ertele. Tekrarlayan alarmın asıl zamanı bozulmaz, ertelenen ayrı tutulur."""
        if note_id not in self.store.notes:
            return
        self.withdraw_notification(f"alarm-{note_id}")
        self.store.update(note_id, touch=False, notify=True, snooze=time.time() + minutes * 60)
        win = self.note_windows.get(note_id)
        if win:
            win.stop_ring()
            win.refresh_alarm()

    def _fire_alarm(self, note, missed, snoozed=False):
        note_id, now = note["id"], time.time()
        fields = {"snooze": None}
        if not snoozed:
            repeat = note.get("alarm_repeat")
            fields["alarm"] = advance_alarm(note["alarm"], repeat, now) if repeat else None
        self.store.update(note_id, touch=False, notify=True, **fields)
        lines = note["text"].strip().lstrip("•☐☑ ").split("\n")
        title = (_("⏰ Missed alarm: ") if missed else "⏰ ") + (lines[0][:60] or _("Note"))
        notification = Gio.Notification.new(title)
        if len(lines) > 1:
            notification.set_body("\n".join(lines[1:4])[:200])
        notification.set_priority(Gio.NotificationPriority.HIGH)
        notification.set_default_action_and_target("app.open-note", GLib.Variant("s", note_id))
        notification.add_button_with_target(_("Snooze {n} min").format(n=SNOOZE_MINUTES), "app.snooze",
                                            GLib.Variant("s", note_id))
        notification.set_icon(Gio.ThemedIcon.new(APP_ID))
        self.send_notification(f"alarm-{note_id}", notification)
        if self.settings.get("alarm_sound"):
            sound.play_alarm()
        self.open_note(note_id)
        win = self.note_windows.get(note_id)
        if win:
            win.refresh_alarm()
            win.ring()   # hangi notun çaldığı belli olsun diye pencereyi salla
