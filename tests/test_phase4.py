"""Run: python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import skia  # noqa: E402

from engine.characters import load_rig  # noqa: E402
from engine.config import load_style  # noqa: E402
from engine.overlays import OverlayRenderer, _font, wrap  # noqa: E402
from engine.poses import PoseLibrary  # noqa: E402
from engine.renderer import speaker_tags  # noqa: E402
from engine.schema import Character, Screenplay, Shot  # noqa: E402

SP = Screenplay.model_validate({
    "title": "t", "series": {"name": "Test Show", "episode": 2, "clock": "18:30"},
    "scenes": [{"id": "s", "shots": [{"duration": 1, "poll": [1]}]}],
    "ending": {"type": "poll", "badge": "DAY 3", "cta": "Comment 1 or 2",
               "options": ["First", {"text": "Second", "detail": "more"}]}})


def shot(is_ending=False, **kw):
    return SimpleNamespace(shot=Shot(**kw), start=0.0, end=1.0, clock="18:30", is_ending=is_ending)


class TestOverlays(unittest.TestCase):
    def test_wrap_respects_width(self):
        f = _font("library/fonts/Montserrat-Black.ttf", 60)
        for line in wrap("never open the doors after dark no matter what", f, 600):
            self.assertLessEqual(f.measureText(line), 600)

    def test_draws_badge_card_poll_and_end(self):
        tl = SimpleNamespace(shots=[shot(poll=[1]), shot(True)])
        o = OverlayRenderer(SP, tl, load_style("dark_miniseries"))
        self.assertEqual([x.text for x in SP.ending.option_list()], ["First", "Second"])
        surf = skia.Surface(1080, 1920)
        c = surf.getCanvas()
        c.clear(skia.ColorTRANSPARENT)
        o.draw(c, shot(card={"title": "Rule #1", "text": "Stay inside"}, poll=[1]), 0.8)
        o.draw(c, tl.shots[1], 0.8)
        a = surf.makeImageSnapshot().toarray()
        self.assertGreater(a[..., 3].sum(), 0)

    def test_overlays_off_hides_badge(self):
        o = OverlayRenderer(SP, SimpleNamespace(shots=[]), load_style("miniseries"))
        surf = skia.Surface(1080, 1920)
        surf.getCanvas().clear(skia.ColorTRANSPARENT)
        o.draw_badge(surf.getCanvas(), shot(overlays=False), 0.5)
        self.assertEqual(surf.makeImageSnapshot().toarray()[..., 3].sum(), 0)

    def test_speaker_tags_cycle_colors(self):
        chars = [Character(id="a", label="AL"), Character(id="b"), Character(id="c", tag_color="#123456")]
        tags = speaker_tags(chars, load_style("miniseries"))
        self.assertEqual(tags["a"][0], "AL")
        self.assertEqual(tags["b"][0], "B")
        self.assertEqual(tags["c"][1], "#123456")
        self.assertNotEqual(tags["a"][1], tags["b"][1])


class TestTallRig(unittest.TestCase):
    def test_variant_merges_and_overrides_poses(self):
        base, tall = load_rig(), load_rig("tall")
        self.assertGreater(tall["height"], base["height"])
        self.assertGreater(tall["arm"]["upper"], base["arm"]["upper"])
        self.assertIn("accessories", tall)            # untouched sections kept
        lib = PoseLibrary(tall["pose_overrides"])
        self.assertEqual(lib.pose("phone_ear", 0).arm_r, [100.0, -225.0])

    def test_dark_preset_uses_tall(self):
        self.assertEqual(load_style("dark_miniseries")["character"]["rig"], "tall")


if __name__ == "__main__":
    unittest.main()
