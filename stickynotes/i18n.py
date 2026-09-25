"""Çeviri altyapısı (gettext). Kaynak dil İngilizce; Türkçe ikinci dil.

Dil, sistemin dil ayarından alınır (LANGUAGE / LC_ALL / LC_MESSAGES / LANG). Deneme için
STICKYNOTES_LANG=tr ya da =en ile zorlanabilir. Çeviri bulunamazsa İngilizce gösterilir.
"""
import gettext
import os

DOMAIN = "sticky-notes"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _locale_dirs():
    return [os.environ.get("STICKYNOTES_LOCALEDIR"), os.path.join(_ROOT, "locale"),
            "/app/share/locale", "/usr/share/locale", "/usr/local/share/locale"]


def _languages():
    forced = os.environ.get("STICKYNOTES_LANG")
    if forced:
        return [forced]
    from gi.repository import GLib
    return list(GLib.get_language_names())


def _load():
    languages = _languages()
    for directory in _locale_dirs():
        if directory and os.path.isdir(directory):
            try:
                return gettext.translation(DOMAIN, directory, languages=languages)
            except OSError:
                continue
    return gettext.NullTranslations()


_translation = _load()


def _(message):
    """Metni geçerli dile çevirir."""
    return _translation.gettext(message)


def ngettext(singular, plural, n):
    return _translation.ngettext(singular, plural, n)


def N_(message):
    """Çeviri için işaretler ama şimdi çevirmez (çeviri kullanım anında _() ile yapılır)."""
    return message


def current_language():
    """Kullanılan çeviri dili ('tr' gibi); çeviri yoksa 'en'."""
    info = getattr(_translation, "info", lambda: {})()
    return info.get("language", "en") if isinstance(info, dict) else "en"
