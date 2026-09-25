import unittest
from urllib.parse import parse_qs, unquote, urlsplit

from tests import helpers

helpers.isolate_dirs()
import stickynotes  # noqa: E402
from stickynotes.feedback import ISSUES_URL, build_issue_url, build_mailto, compose, valid_address  # noqa: E402


class FeedbackTests(unittest.TestCase):
    def test_valid_address(self):
        for good in ("a@b.co", "  ad.soyad@ornek.com ", "x+y@sub.domain.org"):
            self.assertTrue(valid_address(good), good)
        for bad in ("", "abc", "a@b", "a b@c.com", "@x.com", "a@@b.com", "a@b@c.com"):
            self.assertFalse(valid_address(bad), bad)

    def test_mailto_encodes_turkish_and_newlines(self):
        info = "Uygulama: 0.1.0\nKurulum: yerel"
        url = build_mailto("dev@ornek.com", "Merhaba,\nşğüıöç İ öneri: 100%", info)
        parts = urlsplit(url)
        self.assertEqual(parts.scheme, "mailto")
        self.assertEqual(parts.path, "dev@ornek.com")
        query = parse_qs(parts.query)
        self.assertEqual(query["subject"], ["Deluxe Sticky Notes feedback"])
        body = query["body"][0]
        self.assertIn("şğüıöç İ öneri: 100%", body)
        self.assertIn("Merhaba,\n", body)
        self.assertTrue(body.endswith("Kurulum: yerel\n"))
        self.assertNotIn(" ", url)          # boşluklar yüzde-kodlanmış

    def test_issue_url_prefills_title_and_body(self):
        url = build_issue_url("Kartlara sürükleyerek sıralama\nşğüıöç detay", "App: 0.1.0")
        parts = urlsplit(url)
        self.assertEqual(f"{parts.scheme}://{parts.netloc}{parts.path}", ISSUES_URL)
        query = parse_qs(parts.query)
        self.assertEqual(query["title"], ["Kartlara sürükleyerek sıralama"])
        self.assertIn("şğüıöç detay", query["body"][0])
        self.assertTrue(query["body"][0].endswith("App: 0.1.0\n"))
        self.assertNotIn(" ", url)

    def test_issue_title_is_capped_and_falls_back(self):
        long_title = build_issue_url("x" * 300, "i")
        self.assertLessEqual(len(parse_qs(urlsplit(long_title).query)["title"][0]), 80)
        empty = build_issue_url("   ", "i")
        self.assertEqual(parse_qs(urlsplit(empty).query)["title"], ["Deluxe Sticky Notes feedback"])

    def test_no_personal_email_in_source(self):
        import os
        root = helpers.ROOT
        for folder, _dirs, files in os.walk(os.path.join(root, "stickynotes")):
            for name in files:
                if name.endswith((".py", ".xml", ".desktop")):
                    self.assertNotIn("gmail.com", open(os.path.join(folder, name), encoding="utf-8").read())

    def test_compose_appends_info_but_no_note_content(self):
        text = compose("  öneri  ", "bilgi")
        self.assertEqual(text, "öneri\n\n--\nbilgi\n")


if __name__ == "__main__":
    unittest.main()
