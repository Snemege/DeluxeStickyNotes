import ast
import gettext
import os
import re
import subprocess
import tempfile
import unittest

from tests import helpers

helpers.isolate_dirs()
import stickynotes  # noqa: E402

ROOT = helpers.ROOT
TURKISH_LETTERS = re.compile("[çğıöşüÇĞİÖŞÜ]")
MARKERS = {"_", "N_", "ngettext"}


def source_files():
    folder = os.path.join(ROOT, "stickynotes")
    return [os.path.join(folder, n) for n in sorted(os.listdir(folder)) if n.endswith(".py")]


def collect(path):
    """(çevrilebilir msgid'ler, çeviri işaretçisi dışındaki Türkçe harfli metinler)"""
    tree = ast.parse(open(path, encoding="utf-8").read())
    marked, stray = set(), []
    inside = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) in MARKERS:
            plural = node.func.id == "ngettext"
            for index, arg in enumerate(node.args[:2] if plural else node.args[:1]):
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if index == 0:                      # çoğul biçim aynı kaydın parçasıdır
                        marked.add(arg.value)
                    inside.add(id(arg))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
                docstrings.add(id(first.value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in inside
                and id(node) not in docstrings and TURKISH_LETTERS.search(node.value)):
            stray.append((os.path.basename(path), node.lineno, node.value))
    return marked, stray


def load_catalog(lang="tr", localedir=None):
    return gettext.translation("sticky-notes", localedir or os.path.join(ROOT, "locale"), languages=[lang])


class TranslationTests(unittest.TestCase):
    def test_every_marked_string_is_translated_to_turkish(self):
        catalog = load_catalog()._catalog
        missing = []
        for path in source_files():
            for msgid in collect(path)[0]:
                if msgid not in catalog and not any(k[0] == msgid for k in catalog if isinstance(k, tuple)):
                    missing.append((os.path.basename(path), msgid))
        self.assertEqual(missing, [], "Çevrilmemiş metinler var: ./tools/update-translations.sh çalıştır")

    def test_no_turkish_literals_left_outside_gettext(self):
        allowed = {"İ", "ı", "İ", "Deluxe Yapışkan Notlar"}      # arama katlaması ve masaüstü girdisinin Türkçe adı
        stray = []
        for path in source_files():
            for entry in collect(path)[1]:
                if entry[2] in allowed or "Name[tr]" in entry[2]:
                    continue
                stray.append(entry)
        self.assertEqual(stray, [], "Kaynakta çeviri dışı Türkçe metin kalmış (İngilizce yazıp _() ile sar)")

    def test_no_empty_or_fuzzy_translations(self):
        text = open(os.path.join(ROOT, "po", "tr.po"), encoding="utf-8").read()
        self.assertNotIn("#, fuzzy", text)
        catalog = load_catalog()._catalog
        empty = [k for k, v in catalog.items() if k and not v]
        self.assertEqual(empty, [])

    def test_compiled_mo_matches_the_po_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mo = os.path.join(tmp, "tr", "LC_MESSAGES")
            os.makedirs(mo)
            subprocess.run(["msgfmt", "-o", os.path.join(mo, "sticky-notes.mo"),
                            os.path.join(ROOT, "po", "tr.po")], check=True)
            fresh = load_catalog(localedir=tmp)._catalog
        shipped = load_catalog()._catalog
        self.assertEqual(fresh, shipped, "locale/tr .mo eski: ./tools/update-translations.sh çalıştır")

    def test_turkish_samples_and_english_default(self):
        tr = load_catalog()
        self.assertEqual(tr.gettext("Trash"), "Çöp kutusu")
        self.assertEqual(tr.gettext("Snooze {n} min").format(n=5), "5 dk ertele")
        self.assertEqual(tr.ngettext("{n} note imported", "{n} notes imported", 3).format(n=3), "3 not içe aktarıldı")
        from stickynotes.i18n import _
        self.assertEqual(_("Trash"), "Trash")      # testler STICKYNOTES_LANG=en ile çalışır
        self.assertEqual(_("A string that has no translation"), "A string that has no translation")

    def test_placeholders_are_preserved_in_translations(self):
        catalog = load_catalog()._catalog
        for key, value in catalog.items():
            if not key:
                continue
            msgid = key[0] if isinstance(key, tuple) else key
            self.assertEqual(sorted(re.findall(r"\{\w+\}", msgid)), sorted(re.findall(r"\{\w+\}", value)), msgid)

    def test_desktop_and_metainfo_have_turkish_names(self):
        desktop = open(os.path.join(ROOT, "data", "io.github.vex.StickyNotes.desktop"), encoding="utf-8").read()
        self.assertIn("Name=Deluxe Sticky Notes", desktop)
        self.assertIn("Name[tr]=Deluxe Yapışkan Notlar", desktop)


if __name__ == "__main__":
    unittest.main()
