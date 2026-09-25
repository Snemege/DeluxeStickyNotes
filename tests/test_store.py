import datetime
import os
import time
import unittest

from tests import helpers

helpers.isolate_dirs()
import stickynotes  # noqa: E402
from stickynotes import store as S  # noqa: E402


class StoreTests(unittest.TestCase):
    def setUp(self):
        helpers.isolate_dirs()
        self.store = S.NoteStore()

    def make(self, text):
        note = self.store.create()
        self.store.update(note["id"], text=text)
        return note

    def test_save_and_reload(self):
        a = self.make("birinci")
        self.store.save_now()
        self.assertEqual(S.NoteStore().notes[a["id"]]["text"], "birinci")

    def test_delete_moves_to_trash_and_restore(self):
        a = self.make("x")
        note = self.store.delete(a["id"])
        self.assertNotIn(a["id"], self.store.notes)
        self.assertIn(a["id"], self.store.trash)
        self.assertEqual(self.store.trash_days_left(note), S.TRASH_DAYS)
        self.store.trash_restore(a["id"])
        self.assertIn(a["id"], self.store.notes)
        self.assertNotIn("deleted", self.store.notes[a["id"]])

    def test_trash_survives_reload_and_purges_after_30_days(self):
        a = self.make("x")
        self.store.delete(a["id"])
        self.store.save_now()
        store2 = S.NoteStore()
        self.assertIn(a["id"], store2.trash)
        store2.trash[a["id"]]["deleted"] = time.time() - (S.TRASH_DAYS + 1) * 86400
        store2.save_now()
        self.assertNotIn(a["id"], S.NoteStore().trash)

    def test_undo_restore_of_deleted_note(self):
        a = self.make("x")
        note = self.store.delete(a["id"])
        self.store.restore(note)
        self.assertIn(a["id"], self.store.notes)
        self.assertNotIn(a["id"], self.store.trash)

    def test_trash_delete_and_empty(self):
        ids = [self.make(t)["id"] for t in "abc"]
        for i in ids:
            self.store.delete(i)
        self.store.trash_delete(ids[0])
        self.assertEqual(len(self.store.trash), 2)
        self.store.trash_empty()
        self.assertEqual(len(self.store.trash), 0)

    def test_daily_backup_is_created_and_pruned(self):
        self.make("x")
        self.store.save_now()
        S.NoteStore()                                   # bugünkü yedek oluşur
        today = f"notes-{datetime.date.today().isoformat()}.json"
        store = S.NoteStore()
        self.assertIn(today, [os.path.basename(p) for p in store._backups()])
        for d in range(1, 12):
            open(os.path.join(store.backup_dir, f"notes-2020-01-{d:02d}.json"), "w").write("{}")
        store._daily_backup()
        os.remove(os.path.join(store.backup_dir, today))
        store._daily_backup()
        self.assertEqual(len(store._backups()), S.BACKUP_KEEP)

    def test_corrupt_file_recovers_from_backup(self):
        a = self.make("kurtarılacak")
        self.store.save_now()
        S.NoteStore()                                   # yedek al
        with open(self.store.path, "w") as f:
            f.write("{bozuk json")
        recovered = S.NoteStore()
        self.assertEqual(recovered.notes[a["id"]]["text"], "kurtarılacak")
        self.assertTrue(recovered.recovered_from)
        self.assertTrue(os.path.exists(recovered.path + ".bad"))
        self.assertTrue(os.path.exists(recovered.path))   # kurtarılan hemen yeniden yazılır

    def test_pinned_notes_sort_first(self):
        a, b, c = self.make("A"), self.make("B"), self.make("C")
        self.store.update(a["id"], touch=False, pinned=True)
        self.store.update(b["id"], text="B'", touch=True)
        order = [n["text"] for n in self.store.sorted_notes()]
        self.assertEqual(order[0], "A")
        self.assertEqual(order[1], "B'")

    def test_settings_defaults_and_persistence(self):
        settings = S.Settings(self.store.dir)
        self.assertTrue(settings.get("alarm_sound"))
        self.assertIsNone(settings.get("background"))
        settings.set("background", True)
        self.assertTrue(S.Settings(self.store.dir).get("background"))


if __name__ == "__main__":
    unittest.main()


class ImportTests(unittest.TestCase):
    def test_import_adds_only_new_notes_and_marks_them_closed(self):
        helpers.isolate_dirs()
        source = S.NoteStore()
        a = source.create(); source.update(a["id"], text="kaynak")
        source.save_now()
        helpers.isolate_dirs()
        target = S.NoteStore()
        self.assertEqual(target.import_from(source.path), 1)
        self.assertEqual(target.notes[a["id"]]["text"], "kaynak")
        self.assertFalse(target.notes[a["id"]]["open"])
        self.assertEqual(target.import_from(source.path), 0)      # ikinci kez eklemez

    def test_import_from_bad_file_raises_value_error(self):
        helpers.isolate_dirs()
        store = S.NoteStore()
        bad = os.path.join(store.dir, "bad.json")
        os.makedirs(store.dir, exist_ok=True)
        open(bad, "w").write("{bozuk")
        with self.assertRaises(ValueError):
            store.import_from(bad)
        with self.assertRaises(ValueError):
            store.import_from(os.path.join(store.dir, "yok.json"))
