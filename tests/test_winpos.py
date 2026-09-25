import unittest

from tests import helpers

helpers.isolate_dirs()
from stickynotes.winpos import bounds_from_state  # noqa: E402

CUR = {"is-current": True}


class BoundsTests(unittest.TestCase):
    def test_two_monitors_one_rotated(self):
        monitors = [
            (("DP-1", "a", "b", "c"), [("m1", 2560, 1440, 60.0, 1.0, [1.0], CUR), ("m0", 1920, 1080, 60.0, 1.0, [1.0], {})], {}),
            (("HDMI-1", "a", "b", "d"), [("m2", 1080, 1920, 60.0, 1.0, [1.0], CUR)], {}),
        ]
        logical = [
            (0, 0, 1.0, 0, True, [("DP-1", "a", "b", "c")], {}),
            (2560, -200, 1.0, 1, False, [("HDMI-1", "a", "b", "d")], {}),   # 90° dönük: 1920x1080
        ]
        self.assertEqual(bounds_from_state(monitors, logical), (0, -200, 4480, 1440))

    def test_scale_is_applied(self):
        monitors = [(("DP-1", "a", "b", "c"), [("m", 3840, 2160, 60.0, 2.0, [2.0], CUR)], {})]
        logical = [(0, 0, 2.0, 0, True, [("DP-1", "a", "b", "c")], {})]
        self.assertEqual(bounds_from_state(monitors, logical), (0, 0, 1920, 1080))

    def test_empty_or_absurd_data_means_no_clamping(self):
        self.assertIsNone(bounds_from_state([], []))
        monitors = [(("X", "a", "b", "c"), [("m", 100, 100, 60.0, 1.0, [1.0], CUR)], {})]
        logical = [(0, 0, 1.0, 0, True, [("X", "a", "b", "c")], {})]
        self.assertIsNone(bounds_from_state(monitors, logical))


if __name__ == "__main__":
    unittest.main()
