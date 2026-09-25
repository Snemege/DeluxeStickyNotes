import os
import tempfile
import unittest

from tests import helpers

helpers.isolate_dirs()
from stickynotes.export import export_all, note_title, note_to_markdown  # noqa: E402


class ExportTests(unittest.TestCase):
    def test_lists_and_bold(self):
        note = {"text": "Başlık\n☐ süt\n☑ ekmek\n• yumurta", "tags": [["bold", 0, 6]]}
        self.assertEqual(note_to_markdown(note),
                         "**Başlık**\n- [ ] süt\n- [x] ekmek\n- yumurta\n")

    def test_markers_never_include_edge_spaces(self):
        note = {"text": "a  b c", "tags": [["bold", 1, 3]]}
        self.assertEqual(note_to_markdown(note), "a  b c\n")   # yalnız boşluk biçimlenmez
        note = {"text": "a  b c", "tags": [["bold", 1, 4]]}
        self.assertEqual(note_to_markdown(note), "a  **b** c\n")   # baştaki boşluklar işaretin dışında
        note = {"text": "x kalın y", "tags": [["bold", 1, 8]]}
        self.assertEqual(note_to_markdown(note), "x **kalın** y\n")

    def test_bullet_prefix_is_not_formatted(self):
        note = {"text": "☐ görev", "tags": [["bold", 0, 7]]}
        self.assertEqual(note_to_markdown(note), "- [ ] **görev**\n")

    def test_crossing_styles_are_split_per_run(self):
        out = note_to_markdown({"text": "abcdefgh", "tags": [["bold", 0, 5], ["italic", 3, 8]]})
        self.assertTrue(out.startswith("**abc**"))
        self.assertIn("de", out)
        self.assertEqual(out.replace("*", ""), "abcdefgh\n")

    def test_title_and_empty(self):
        self.assertEqual(note_title({"text": "☐ Alışveriş\nsüt"}), "Alışveriş")
        self.assertEqual(note_title({"text": ""}), "Untitled note")
        self.assertEqual(note_to_markdown({"text": "", "tags": []}), "\n")

    def test_export_all_unique_safe_filenames(self):
        folder = tempfile.mkdtemp()
        notes = [{"text": "Aynı / başlık?", "tags": []}] * 2 + [{"text": "", "tags": []}]
        self.assertEqual(export_all(notes, folder), 3)
        names = sorted(os.listdir(folder))
        self.assertEqual(len(set(names)), 3)
        self.assertTrue(all(n.endswith(".md") and "/" not in n for n in names))


if __name__ == "__main__":
    unittest.main()
