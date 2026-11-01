"""Run: python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import skia  # noqa: E402

from engine.characters import CharacterRenderer, parse_accessories, load_rig, resolve_character  # noqa: E402
from engine.config import load_style  # noqa: E402
from engine.poses import Blinker, PoseLibrary  # noqa: E402
from engine.schema import Character  # noqa: E402


class TestPoses(unittest.TestCase):
    def setUp(self):
        self.lib = PoseLibrary()

    def test_all_poses_and_expressions_evaluate(self):
        for name in self.lib.names():
            for t in (0.0, 0.1, 0.5, 2.0):
                p = self.lib.pose(name, t, speaking=1.0)
                self.assertEqual(len(p.arm_l), 2)
        for name in self.lib.expressions:
            self.lib.expression(name)

    def test_keyframes_hold_last_value(self):
        p = self.lib.pose("point", 5.0)
        self.assertAlmostEqual(p.arm_r[0], 95.0)

    def test_unknown_pose_falls_back_to_idle(self):
        self.assertEqual(self.lib.pose("nope", 0).leg_l, self.lib.pose("idle", 0).leg_l)

    def test_blink_is_deterministic(self):
        a, b = Blinker("x", 2, 4, 0.13), Blinker("x", 2, 4, 0.13)
        self.assertEqual(a.times[:5], b.times[:5])


class TestCharacters(unittest.TestCase):
    def test_accessory_parsing(self):
        acc = parse_accessories(["helmet_red_stripe", "cap:#123456"], load_rig())
        self.assertEqual(acc[0].kind, "helmet")
        self.assertEqual(acc[0].params["stripe"], "#C8432B")
        self.assertEqual((acc[1].kind, acc[1].params["color"]), ("cap", "#123456"))

    def test_library_merge_keeps_overrides(self):
        ch = resolve_character(Character(id="c", library="delivery_guy", label="BOB"))
        self.assertEqual(ch.label, "BOB")
        self.assertIn("helmet_red_stripe", ch.look.accessories)

    def test_draw_returns_hand_anchors_and_pixels(self):
        ch = resolve_character(Character(id="c", library="store_clerk"))
        r = CharacterRenderer(ch, load_style("miniseries"))
        lib = PoseLibrary()
        arr = np.zeros((1920, 1080, 4), dtype=np.uint8)
        surf = skia.Surface(arr, colorType=skia.kRGBA_8888_ColorType)
        a = r.draw(surf.getCanvas(), 540, 1650, 1920, 1.0, lib.pose("hold_up", 0.5), lib.expression("shock"),
                   0.5, mouth_open=0.7)
        self.assertLess(a["hand_r"][1], a["head"][1])      # raised hand above head center
        self.assertGreater(a["hand_r"][0], 540)            # right arm on screen-right
        self.assertGreater(arr[..., 3].sum(), 0)


if __name__ == "__main__":
    unittest.main()
