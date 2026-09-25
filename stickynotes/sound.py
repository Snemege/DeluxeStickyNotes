import os
import shutil

from gi.repository import Gio, Gtk

ALARM_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alarm.wav")

# Tek bir kalıcı çalıcı nesnesi yeniden kullanılır: her alarmda yenisini oluşturup listede tutmak
# PyGObject ile GTK medya nesnesinin sahiplik sayımını karıştırıyordu.
_media = None


def _player():
    """Gtk.MediaFile (yoksa/hatalıysa False)."""
    global _media
    if _media is None:
        media = Gtk.MediaFile.new_for_filename(ALARM_FILE)
        _media = media if media.get_error() is None else False
    return _media


def _fallback_player():
    for cmd in (["pw-play"], ["paplay"], ["canberra-gtk-play", "-f"], ["aplay", "-q"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


def stop_alarm():
    media = _media
    if media and media.get_playing():
        media.pause()


def play_alarm():
    """Alarm sesini çalar. Gtk.MediaFile çalışmazsa sistemdeki bir oynatıcıya düşer."""
    media = _player()
    if media:
        if media.is_seekable():
            media.seek(0)                # her alarm baştan çalsın
        media.play()
        return True
    player = _fallback_player()
    if player:
        Gio.Subprocess.new(player + [ALARM_FILE], Gio.SubprocessFlags.NONE)
        return True
    return False
