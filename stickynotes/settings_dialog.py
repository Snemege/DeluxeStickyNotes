from gi.repository import Adw, Gtk

from . import sound
from .i18n import _


class SettingsDialog(Adw.PreferencesDialog):
    def __init__(self, app):
        super().__init__(title=_("Settings"))
        self.app = app
        self._busy = False

        self.bg_row = Adw.SwitchRow(
            title=_("Run in the background"),
            subtitle=_("Alarms keep working and notes stay open even if the main window is closed"),
            active=bool(app.settings.get("background")),
        )
        self.auto_row = Adw.SwitchRow(
            title=_("Start automatically at login"),
            subtitle=_("Open notes come back; the main window stays closed"),
            active=bool(app.settings.get("autostart")),
        )
        self.bg_row.connect("notify::active", self._on_background)
        self.auto_row.connect("notify::active", self._on_autostart)

        group = Adw.PreferencesGroup(title=_("Background"))
        group.add(self.bg_row)
        group.add(self.auto_row)
        self.sound_row = Adw.SwitchRow(
            title=_("Alarm sound"), subtitle=_("Play a sound when an alarm rings"),
            active=bool(app.settings.get("alarm_sound")),
        )
        self.sound_row.connect(
            "notify::active", lambda row, _p: app.settings.set("alarm_sound", row.get_active()))
        try_row = Adw.ActionRow(title=_("Try the alarm sound"))
        try_btn = Gtk.Button(label=_("Play"), valign=Gtk.Align.CENTER)
        try_btn.connect("clicked", lambda _b: sound.play_alarm())
        try_row.add_suffix(try_btn)
        sound_group = Adw.PreferencesGroup(title=_("Alarm"))
        sound_group.add(self.sound_row)
        sound_group.add(try_row)

        self.shortcut_row = Adw.SwitchRow(
            title=_("Global shortcuts"),
            subtitle=_("Ctrl+Alt+N: new note · Ctrl+Alt+A: all notes. GNOME asks you to confirm the "
                       "shortcuts when you turn this on; start the app from the app menu."),
            active=bool(app.settings.get("global_shortcuts")))
        self.shortcut_row.connect("notify::active", lambda row, _p: app.set_global_shortcuts(row.get_active()))
        shortcut_group = Adw.PreferencesGroup(title=_("Shortcuts"))
        shortcut_group.add(self.shortcut_row)

        page = Adw.PreferencesPage()
        page.add(group)
        page.add(sound_group)
        page.add(shortcut_group)
        self.add(page)

    def _on_background(self, row, _pspec):
        if self._busy:
            return
        self.app.set_background(row.get_active())
        if not row.get_active() and self.auto_row.get_active():
            self.auto_row.set_active(False)

    def _on_autostart(self, row, _pspec):
        if self._busy:
            return
        want = row.get_active()
        if not self.app.set_autostart(want):
            self._busy = True
            row.set_active(not want)
            self._busy = False
            self.add_toast(Adw.Toast(title=_("Couldn't set up autostart")))
            return
        if want and not self.bg_row.get_active():
            self.bg_row.set_active(True)
