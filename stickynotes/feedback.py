"""Geliştiriciye öneri/geri bildirim: yazı kutusu + e-posta (mailto) ya da panoya kopyalama."""
import os
import platform

from gi.repository import Adw, Gdk, GLib, Gtk

from . import __version__, background
from .i18n import _

SUBJECT = _("Deluxe Sticky Notes feedback")
DEFAULT_FEEDBACK_EMAIL = "snemege@gmail.com"


def system_info():
    """Geliştiricinin sorunu anlamasına yarayan teknik bilgi (not içeriği içermez). Geliştiriciye gittiği
    için çevrilmez."""
    from gi.repository import Gdk as _Gdk
    display = _Gdk.Display.get_default()
    return "\n".join([
        f"App: {__version__}",
        f"Install: {'Flatpak' if background.in_flatpak() else 'local'}",
        f"Desktop: {os.environ.get('XDG_CURRENT_DESKTOP', '?')} ({os.environ.get('XDG_SESSION_TYPE', '?')})",
        f"Window backend: {type(display).__name__ if display else '?'}",
        f"GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}, libadwaita "
        f"{Adw.get_major_version()}.{Adw.get_minor_version()}",
        f"System: {platform.system()} {platform.release()}",
    ])


def compose(message, info):
    return f"{message.strip()}\n\n--\n{info}\n"


def build_mailto(address, message, info):
    """mailto: bağlantısı; Türkçe karakterler ve satır sonları yüzde-kodlanır."""
    escape = lambda text: GLib.Uri.escape_string(text, None, True)   # noqa: E731
    return f"mailto:{address}?subject={escape(SUBJECT)}&body={escape(compose(message, info))}"


def valid_address(address):
    address = address.strip()
    if not address or " " in address or address.count("@") != 1:
        return False
    local, domain = address.split("@")
    return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".")


class FeedbackDialog(Adw.Dialog):
    def __init__(self, settings):
        super().__init__(title=_("Suggest to the developers"), content_width=460, content_height=560)
        self.settings = settings
        self.info = system_info()

        self.text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=10, right_margin=10,
                                 top_margin=10, bottom_margin=10, vexpand=True)
        self.text.get_buffer().connect("changed", lambda *_: self._update_buttons())
        frame = Gtk.ScrolledWindow(child=self.text, min_content_height=150, vexpand=True,
                                   css_classes=["card"])

        self.email_row = Adw.EntryRow(title=_("Email address the feedback goes to"),
                                      text=settings.get("feedback_email") or DEFAULT_FEEDBACK_EMAIL)
        self.email_row.connect("changed", self._on_email_changed)
        group = Adw.PreferencesGroup()
        group.add(self.email_row)

        info_label = Gtk.Label(label=_("This technical information is added to your message (the contents of your notes are never sent):") + "\n\n"
                                     + self.info, xalign=0, wrap=True, selectable=True,
                               css_classes=["caption", "dim-label"])

        self.copy_btn = Gtk.Button(label=_("Copy to clipboard"))
        self.copy_btn.connect("clicked", self._on_copy)
        self.send_btn = Gtk.Button(label=_("Send by email"), css_classes=["suggested-action"])
        self.send_btn.connect("clicked", self._on_send)
        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        buttons.append(self.copy_btn)
        buttons.append(self.send_btn)

        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)
        box.append(Gtk.Label(label=_("Write your suggestion, the bug you found, or a missing feature:"), xalign=0))
        box.append(frame)
        box.append(group)
        box.append(info_label)
        box.append(self.status)
        box.append(buttons)

        view = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=box, hscrollbar_policy=Gtk.PolicyType.NEVER))
        view.add_top_bar(Adw.HeaderBar())
        self.set_child(view)
        self._update_buttons()

    def message(self):
        buf = self.text.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _on_email_changed(self, row):
        self.settings.set("feedback_email", row.get_text().strip())
        self._update_buttons()

    def _update_buttons(self):
        has_text = bool(self.message().strip())
        self.copy_btn.set_sensitive(has_text)
        self.send_btn.set_sensitive(has_text and valid_address(self.email_row.get_text()))
        if has_text and not valid_address(self.email_row.get_text()):
            self.status.set_label(_("To send by email, enter a valid address above, or copy to the clipboard."))
        else:
            self.status.set_label("")

    def _on_copy(self, _btn):
        Gdk.Display.get_default().get_clipboard().set(compose(self.message(), self.info))
        self.status.set_label(_("Copied to the clipboard."))

    def _on_send(self, _btn):
        uri = build_mailto(self.email_row.get_text().strip(), self.message(), self.info)
        Gtk.UriLauncher.new(uri).launch(self.get_root(), None, self._on_launched)

    def _on_launched(self, launcher, result):
        try:
            launcher.launch_finish(result)
            self.status.set_label(_("Your email app opened; send it from there."))
        except GLib.Error:
            self.status.set_label(_("Couldn't open an email app. Use “Copy to clipboard” and send it yourself."))
