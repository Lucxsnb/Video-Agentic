"""Run: python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from engine.audio_mix import db_to_gain, duck_gain, place  # noqa: E402
from engine.config import load_style  # noqa: E402
from engine.music import generate, load_moods, triad  # noqa: E402
from engine.schema import Shot  # noqa: E402
from engine.sfx import GENERATORS, get_sfx  # noqa: E402
from engine.soundtrack import sfx_cues  # noqa: E402

SR = 48000


class TestSfx(unittest.TestCase):
    def test_all_generators_are_clean(self):
        for name in GENERATORS:
            x = get_sfx(name, SR)
            self.assertGreater(len(x), 100, name)
            self.assertFalse(np.isnan(x).any(), name)
            self.assertLessEqual(float(np.abs(x).max()), 1.0, name)
            self.assertLess(abs(float(x[0])), 0.05, f"{name} starts with a click")

    def test_unknown_raises(self):
        with self.assertRaises(KeyError):
            get_sfx("no_such_sound", SR)


class TestMusic(unittest.TestCase):
    def test_moods_generate(self):
        for mood in load_moods():
            x = generate(mood, 4.0, SR, 1)
            self.assertEqual(len(x), int(4.0 * SR) + 1)
            self.assertAlmostEqual(float(np.abs(x).max()), 0.8, places=2)

    def test_deterministic(self):
        self.assertTrue(np.array_equal(generate("sad", 2, SR, 3), generate("sad", 2, SR, 3)))

    def test_triad_minor(self):
        self.assertEqual(triad(45, [0, 2, 3, 5, 7, 8, 10], 1), [45, 48, 52])


class TestMix(unittest.TestCase):
    def test_duck_drops_under_voice(self):
        v = np.zeros(SR * 3, np.float32)
        v[SR:2 * SR] = 0.3 * np.sin(np.arange(SR) * 0.05)
        g = duck_gain(v, SR, -10, -40, 0.05, 0.3)
        self.assertAlmostEqual(float(g[SR // 2]), 1.0, places=2)
        self.assertAlmostEqual(float(g[int(1.8 * SR)]), db_to_gain(-10), places=2)

    def test_place_clips_negative_start(self):
        buf = np.zeros(10, np.float32)
        place(buf, np.ones(5, np.float32), -2 / SR, SR)
        self.assertEqual(buf[:4].tolist(), [1, 1, 1, 0])


class TestAutoSfx(unittest.TestCase):
    def test_cues_follow_screen_events(self):
        def st(start, end, **kw):
            return SimpleNamespace(shot=Shot(**kw), start=start, end=end, duration=end - start,
                                   scene_id="s", is_ending=False)
        shots = [st(0, 2, transition_out="whip", camera={"punch": 0.8},
                    props=[{"svg": "phone_incoming_call", "anim": "ring"}]),
                 st(2, 4, card={"text": "x", "at": 0.5}, poll=[1], sfx=[{"name": "tick", "at": 0.2}]),
                 st(4, 6, poll=[1, 2], auto_sfx=False)]
        shots.append(SimpleNamespace(shot=Shot(), start=6, end=8, duration=2, scene_id="e", is_ending=True))
        cues = sfx_cues(SimpleNamespace(shots=shots), load_style("dark_miniseries"))
        names = [(round(c.t, 2), c.name) for c in cues]
        self.assertIn((1.8, "whoosh"), names)
        self.assertIn((0.0, "hit"), names)
        self.assertIn((0.0, "ring"), names)
        self.assertIn((2.5, "pop"), names)
        self.assertIn((2.2, "tick"), names)
        self.assertIn((6.0, "boom"), names)
        self.assertNotIn((4.0, "pop"), names)      # auto_sfx off for that shot
        ring = next(c for c in cues if c.name == "ring")
        self.assertEqual(ring.params, {"dur": 2.0})


if __name__ == "__main__":
    unittest.main()
