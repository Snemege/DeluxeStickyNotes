import time
import unittest

from tests import helpers

helpers.isolate_dirs()
import stickynotes  # noqa: E402
from gi.repository import GLib  # noqa: E402
from stickynotes.store import advance_alarm, next_alarm_time  # noqa: E402


class AlarmMathTests(unittest.TestCase):
    def test_daily_skips_missed_days(self):
        now = time.time()
        nxt = advance_alarm(now - 3 * 86400 - 600, "daily", now)
        self.assertGreater(nxt, now)
        self.assertLessEqual(nxt - now, 86400)

    def test_weekly(self):
        now = time.time()
        nxt = advance_alarm(now - 10 * 86400, "weekly", now)
        self.assertGreater(nxt, now)
        self.assertLessEqual(nxt - now, 7 * 86400)

    def test_wall_clock_preserved_across_dst(self):
        import os
        old = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Berlin"
        time.tzset()
        try:
            start = GLib.DateTime.new_local(2026, 3, 28, 9, 0, 0).to_unix()
            now = GLib.DateTime.new_local(2026, 3, 28, 12, 0, 0).to_unix()
            nxt = GLib.DateTime.new_from_unix_local(advance_alarm(start, "daily", now))
            self.assertEqual((nxt.get_day_of_month(), nxt.get_hour()), (29, 9))   # 29.03'te saat ileri alınır
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()

    def test_next_alarm_time_picks_earliest(self):
        self.assertIsNone(next_alarm_time({}))
        self.assertEqual(next_alarm_time({"alarm": 200, "snooze": 100}), 100)
        self.assertEqual(next_alarm_time({"alarm": 200, "snooze": None}), 200)


if __name__ == "__main__":
    unittest.main()
