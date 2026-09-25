from gi.repository import Gdk, Gtk

from .note_window import FONT_SIZES
from .store import COLORS

FG = "#2b2b2b"


def _build_css():
    css = """
    button.note-card { border-radius: 12px; padding: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.35); }
    button.note-card:hover { filter: brightness(.96); }
    button.swatch { min-width: 28px; min-height: 28px; padding: 0; border-radius: 999px;
                    border: 1px solid rgba(0,0,0,.25); }
    .note-bar button:checked { background: rgba(0,0,0,.18); }
    .note-lock-strip { padding: 0 6px; }
    separator.note-sep { background: rgba(0,0,0,.28); min-height: 1px; }
    .note-bar button { padding: 4px 6px; min-width: 26px; }
    headerbar.note-header button { min-width: 24px; min-height: 24px; padding: 3px 5px; }
    headerbar.note-header { padding: 0 4px; min-height: 40px; }
    window.background headerbar.note-header menubutton.alarm-set > button.toggle {
        background-color: #c2410c; background-image: none; color: #ffffff; font-weight: 700;
        border-radius: 999px; padding: 2px 10px; }
    window.background headerbar.note-header menubutton.alarm-set > button.toggle label { color: #ffffff; }
    label.alarm-pill { background: #c2410c; color: #ffffff; font-weight: 700;
        border-radius: 999px; padding: 1px 10px; }
    window.background popover button:not(.suggested-action):not(.destructive-action),
    window.background popover button label { color: @popover_fg_color; }
    window.background popover button.destructive-action { color: @destructive_fg_color; }
    .shake-a { transform: translate(-12px, 0) rotate(-2.2deg); }
    .shake-b { transform: translate(12px, 0) rotate(2.2deg); }
    window.background.ring-flash { background-image: linear-gradient(rgba(255,90,0,.38), rgba(255,90,0,.38)); }
    """
    for px in FONT_SIZES:
        css += f"window.fs-{px} textview {{ font-size: {px}px; }}\n"
    for name, (_label, bg) in COLORS.items():
        css += f"""
        window.background.note-{name} {{ background-color: {bg}; color: {FG}; }}
        window.note-{name} headerbar, window.note-{name} .note-bar {{ color: {FG}; }}
        window.note-{name} button {{ color: {FG}; }}
        window.note-{name} textview, window.note-{name} textview text {{
            background: transparent; color: {FG}; }}
        button.note-card.note-{name} {{ background: {bg}; color: {FG}; }}
        button.swatch-{name} {{ background: {bg}; }}
        """
    return css


def load_css():
    provider = Gtk.CssProvider()
    provider.load_from_string(_build_css())
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
