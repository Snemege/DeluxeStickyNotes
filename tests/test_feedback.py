import unittest
from urllib.parse import parse_qs, unquote, urlsplit

from tests import helpers

helpers.isolate_dirs()
import stickynotes  # noqa: E402
from stickynotes.feedback import build_mailto, compose, valid_address  # noqa: E402


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

    def test_compose_appends_info_but_no_note_content(self):
        text = compose("  öneri  ", "bilgi")
        self.assertEqual(text, "öneri\n\n--\nbilgi\n")


if __name__ == "__main__":
    unittest.main()
