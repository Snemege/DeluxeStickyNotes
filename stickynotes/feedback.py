"""Geliştiriciye öneri/geri bildirim: yazı kutusu + e-posta (mailto) ya da panoya kopyalama."""
import os
import platform

from gi.repository import Adw, Gdk, GLib, Gtk

from . import __version__, background
from .i18n import _

SUBJECT = _("Deluxe Sticky Notes feedback")
REPO_URL = "https://github.com/Snemege/deluxe-sticky-notes"
ISSUES_URL = REPO_URL + "/issues/new"


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


def build_issue_url(message, info):
    """GitHub'da hazır doldurulmuş yeni sorun sayfası: başlık mesajın ilk satırı, gövde mesaj + teknik bilgi."""
    escape = lambda text: GLib.Uri.escape_string(text, None, True)   # noqa: E731
    first_line = message.strip().split("\n", 1)[0].strip()
    title = first_line[:80] or SUBJECT
    return f"{ISSUES_URL}?title={escape(title)}&body={escape(compose(message, info))}"


def valid_address(address):
    address = address.strip()
    if not address or " " in address or address.count("@") != 1:
        return False
    local, domain = address.split("@")
    return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".")


class FeedbackDialog(Adw.Dialog):
    def __init__(self, settings):
        super().__init__(title=_("Suggest to the developers"), content_width=460, content_height=600)
        self.settings = settings
        self.info = system_info()

        self.text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=10, right_margin=10,
                                 top_margin=10, bottom_margin=10, vexpand=True)
        self.text.get_buffer().connect("changed", lambda *_: self._update_buttons())
        frame = Gtk.ScrolledWindow(child=self.text, min_content_height=150, vexpand=True,
                                   css_classes=["card"])

        # E-posta isteğe bağlıdır ve yalnızca bu bilgisayarda saklanır (kaynak kodda adres yoktur)
        self.email_row = Adw.EntryRow(title=_("Or send by email to this address (optional)"),
                                      text=settings.get("feedback_email") or "")
        self.email_row.connect("changed", self._on_email_changed)
        group = Adw.PreferencesGroup()
        group.add(self.email_row)

        info_label = Gtk.Label(label=_("This technical information is added to your message (the contents "
                                       "of your notes are never sent):") + "\n\n" + self.info,
                               xalign=0, wrap=True, selectable=True, css_classes=["caption", "dim-label"])

        self.copy_btn = Gtk.Button(label=_("Copy to clipboard"))
        self.copy_btn.connect("clicked", self._on_copy)
        self.mail_btn = Gtk.Button(label=_("Send by email"))
        self.mail_btn.connect("clicked", self._on_send_mail)
        self.github_btn = Gtk.Button(label=_("Open on GitHub"), css_classes=["suggested-action"])
        self.github_btn.connect("clicked", self._on_open_github)
        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        for button in (self.copy_btn, self.mail_btn, self.github_btn):
            buttons.append(button)

        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)
        box.append(Gtk.Label(label=_("Write your suggestion, the bug you found, or a missing feature:"),
                             xalign=0))
        for widget in (frame, info_label, group, self.status, buttons):
            box.append(widget)

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
        valid_email = valid_address(self.email_row.get_text())
        self.copy_btn.set_sensitive(has_text)
        self.github_btn.set_sensitive(has_text)
        self.mail_btn.set_sensitive(has_text and valid_email)
        typed = self.email_row.get_text().strip()
        if has_text and typed and not valid_email:
            self.status.set_label(_("To send by email, enter a valid address above, or copy to the clipboard."))
        else:
            self.status.set_label("")

    def _on_copy(self, _btn):
        Gdk.Display.get_default().get_clipboard().set(compose(self.message(), self.info))
        self.status.set_label(_("Copied to the clipboard."))

    def _launch(self, uri, ok_message, fail_message):
        # Uzun mesajlar bağlantıya sığmayabilir; her ihtimale karşı panoya da kopyalanır
        Gdk.Display.get_default().get_clipboard().set(compose(self.message(), self.info))

        def finished(launcher, result):
            try:
                launcher.launch_finish(result)
                self.status.set_label(ok_message)
            except GLib.Error:
                self.status.set_label(fail_message)

        Gtk.UriLauncher.new(uri).launch(self.get_root(), None, finished)

    def _on_open_github(self, _btn):
        self._launch(build_issue_url(self.message(), self.info),
                     _("Your browser opened; finish the report on GitHub."),
                     _("Couldn't open the browser. Use “Copy to clipboard” and paste it into a new GitHub issue."))

    def _on_send_mail(self, _btn):
        self._launch(build_mailto(self.email_row.get_text().strip(), self.message(), self.info),
                     _("Your email app opened; send it from there."),
                     _("Couldn't open an email app. Use “Copy to clipboard” and send it yourself."))
