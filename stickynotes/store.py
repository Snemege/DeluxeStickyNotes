import datetime
import json
import os
import shutil
import time
import uuid

from gi.repository import GLib

from .i18n import N_

APP_ID = "io.github.Snemege.DeluxeStickyNotes"
LEGACY_APP_IDS = ("io.github.vex.StickyNotes",)   # eski sürümlerin kimliği: veriler bir kez taşınır

TRASH_DAYS = 30      # silinen notlar çöp kutusunda bu kadar gün kalır
BACKUP_KEEP = 7      # en son bu kadar günlük yedek saklanır

# name -> (label, background)
COLORS = {
    "yellow": (N_("Yellow"), "#fff3a3"),
    "pink": (N_("Pink"), "#ffd1dc"),
    "green": (N_("Green"), "#c9f0c0"),
    "blue": (N_("Blue"), "#c5e3ff"),
    "purple": (N_("Purple"), "#e0d0ff"),
    "orange": (N_("Orange"), "#ffd9b0"),
}


def data_home():
    """XDG_DATA_HOME'u her seferinde ortamdan okur (GLib değeri ilk çağrıda önbelleğe alır)."""
    return os.environ.get("XDG_DATA_HOME") or GLib.get_user_data_dir()


REPEAT_DAYS = {"daily": 1, "weekly": 7}
SNOOZE_MINUTES = 5


def next_alarm_time(note):
    """Bildirilecek en yakın zaman (alarm ya da ertelenmiş alarm); yoksa None."""
    times = [t for t in (note.get("alarm"), note.get("snooze")) if t]
    return min(times) if times else None


def advance_alarm(timestamp, repeat, now):
    """Tekrarlayan alarmın bir sonraki (şu andan sonraki) zamanı. Saat dilimi/yaz saati kaymasın
    diye duvar saati korunarak gün eklenir."""
    days = REPEAT_DAYS[repeat]
    dt = GLib.DateTime.new_from_unix_local(int(timestamp))
    while dt.to_unix() <= now:
        dt = dt.add_days(days)
    return dt.to_unix()


class Settings:
    """Uygulama ayarları, notes.json'un yanındaki settings.json içinde."""

    DEFAULTS = {"background": None, "autostart": False, "alarm_sound": True, "global_shortcuts": False, "feedback_email": "",
                "main_width": 720, "main_height": 560, "main_x": None, "main_y": None}

    def __init__(self, directory):
        self.path = os.path.join(directory, "settings.json")
        self.values = dict(self.DEFAULTS)
        try:
            with open(self.path, encoding="utf-8") as f:
                self.values.update(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def get(self, key):
        return self.values.get(key, self.DEFAULTS.get(key))

    def set(self, key, value):
        self.values[key] = value
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.values, f, indent=1)


class NoteStore:
    """Tüm notları tek bir notes.json içinde tutar."""

    def __init__(self):
        self.dir = os.path.join(data_home(), APP_ID)
        self.path = os.path.join(self.dir, "notes.json")
        self.backup_dir = os.path.join(self.dir, "backups")
        self.notes = {}
        self.trash = {}                 # id -> not (+ "deleted" zamanı)
        self.recovered_from = None      # bozuk dosya yedekten kurtarıldıysa yedeğin adı
        self.migrated_from = None       # veriler eski kimlikli bir sürümden taşındıysa o kimlik
        self._migrate_legacy()
        self._listeners = []
        self._save_id = 0
        self._load()
        self._purge_trash()
        self._daily_backup()

    def connect(self, callback):
        self._listeners.append(callback)

    def _notify(self):
        for cb in self._listeners:
            cb()

    def _migrate_legacy(self):
        """Yeni kimlikli sürüm ilk kez açılıyorsa notları/ayarları eski kimliğin klasöründen kopyalar.
        Eski klasöre dokunulmaz (yedek olarak kalır)."""
        if os.path.exists(self.path):
            return
        for legacy in LEGACY_APP_IDS:
            old = os.path.join(data_home(), legacy)
            if not os.path.exists(os.path.join(old, "notes.json")):
                continue
            os.makedirs(self.dir, exist_ok=True)
            for name in ("notes.json", "settings.json"):
                source = os.path.join(old, name)
                if os.path.exists(source):
                    shutil.copy2(source, os.path.join(self.dir, name))
            if os.path.isdir(os.path.join(old, "backups")):
                shutil.copytree(os.path.join(old, "backups"), self.backup_dir, dirs_exist_ok=True)
            self.migrated_from = legacy
            return

    def _read(self, path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        notes = {n["id"]: n for n in data.get("notes", [])}
        trash = {n["id"]: n for n in data.get("trash", [])}
        return notes, trash

    def _backups(self):
        """Yedek dosyaları, en yeniden eskiye."""
        try:
            names = [n for n in os.listdir(self.backup_dir) if n.startswith("notes-") and n.endswith(".json")]
        except FileNotFoundError:
            return []
        return [os.path.join(self.backup_dir, n) for n in sorted(names, reverse=True)]

    def _load(self):
        try:
            self.notes, self.trash = self._read(self.path)
            return
        except FileNotFoundError:
            return
        except (json.JSONDecodeError, KeyError, AttributeError, TypeError):
            os.replace(self.path, self.path + ".bad")     # bozuk dosya silinmez, kenara alınır
        for backup in self._backups():                      # en yeni geçerli yedeği dene
            try:
                self.notes, self.trash = self._read(backup)
                self.recovered_from = os.path.basename(backup)
                self.save_now()                             # kurtarılanı hemen diske yaz
                return
            except (OSError, json.JSONDecodeError, KeyError, AttributeError, TypeError):
                continue

    def _daily_backup(self):
        """Günde bir kez notes.json'un kopyasını alır, son BACKUP_KEEP tanesini saklar."""
        if not os.path.exists(self.path) or not (self.notes or self.trash):
            return
        today = os.path.join(self.backup_dir, f"notes-{datetime.date.today().isoformat()}.json")
        if os.path.exists(today):
            return
        os.makedirs(self.backup_dir, exist_ok=True)
        shutil.copy2(self.path, today)
        for old in self._backups()[BACKUP_KEEP:]:
            os.remove(old)

    def _purge_trash(self):
        limit = time.time() - TRASH_DAYS * 86400
        stale = [i for i, n in self.trash.items() if n.get("deleted", 0) < limit]
        for note_id in stale:
            del self.trash[note_id]
        if stale:
            self._schedule_save()

    def save_now(self):
        if self._save_id:
            GLib.source_remove(self._save_id)
            self._save_id = 0
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "notes": list(self.notes.values()),
                       "trash": list(self.trash.values())}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def _schedule_save(self):
        if not self._save_id:
            self._save_id = GLib.timeout_add(500, self._on_save_timeout)

    def _on_save_timeout(self):
        self._save_id = 0
        self.save_now()
        return GLib.SOURCE_REMOVE

    def create(self, color="yellow"):
        now = time.time()
        note = {
            "id": uuid.uuid4().hex,
            "text": "",
            "tags": [],
            "color": color,
            "width": 380,
            "height": 360,
            "open": True,
            "alarm": None,
            "created": now,
            "modified": now,
        }
        self.notes[note["id"]] = note
        self._schedule_save()
        self._notify()
        return note

    def update(self, note_id, touch=True, notify=None, **fields):
        note = self.notes.get(note_id)
        if note is None:
            return
        note.update(fields)
        if touch:
            note["modified"] = time.time()
        self._schedule_save()
        if touch if notify is None else notify:
            self._notify()

    def delete(self, note_id):
        """Notu çöp kutusuna taşır (kalıcı silmez) ve notu döndürür."""
        note = self.notes.pop(note_id, None)
        if note is not None:
            note["deleted"] = time.time()
            self.trash[note_id] = note
        self._schedule_save()
        self._notify()
        return note

    def restore(self, note):
        """"Geri al": az önce silinen notu yerine koyar."""
        self.trash.pop(note["id"], None)
        note.pop("deleted", None)
        note["open"] = False
        self.notes[note["id"]] = note
        self._schedule_save()
        self._notify()

    def import_from(self, path):
        """Başka bir notes.json'daki (örn. Flatpak dışı kurulum) notları ekler; olanları atlar.
        Eklenen not sayısını döndürür. Okunamazsa ValueError."""
        try:
            notes, trash = self._read(path)
        except (OSError, json.JSONDecodeError, KeyError, AttributeError, TypeError) as exc:
            raise ValueError(str(exc)) from exc
        added = 0
        for note_id, note in notes.items():
            if note_id not in self.notes and note_id not in self.trash:
                note["open"] = False
                self.notes[note_id] = note
                added += 1
        if added:
            self._schedule_save()
            self._notify()
        return added

    def trash_restore(self, note_id):
        note = self.trash.get(note_id)
        if note is not None:
            self.restore(note)

    def trash_delete(self, note_id):
        if self.trash.pop(note_id, None) is not None:
            self._schedule_save()
            self._notify()

    def trash_empty(self):
        self.trash.clear()
        self._schedule_save()
        self._notify()

    def trash_days_left(self, note):
        left = TRASH_DAYS - (time.time() - note.get("deleted", time.time())) / 86400
        return max(0, int(left + 0.999))

    def sorted_notes(self):
        # Sabitlenenler önce, kendi içinde en son değişen başta
        return sorted(self.notes.values(), key=lambda n: (not n.get("pinned"), -n["modified"]))
