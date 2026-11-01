"""Run: python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.captions import CaptionTrack  # noqa: E402
from engine.config import load_style  # noqa: E402
from engine.schema import Screenplay  # noqa: E402
from engine.tts import _merge_to_tokens, tokenize  # noqa: E402


class TestTokens(unittest.TestCase):
    def test_merge_edge_bounds(self):
        toks = tokenize("Hi mom, it's day 13.")
        bounds = [("Hi", 0.1, 0.3), ("mom", 0.3, 0.6), ("it's", 0.8, 1.0), ("day", 1.0, 1.2), ("13", 1.2, 1.6)]
        w = _merge_to_tokens(toks, bounds, 2.0)
        self.assertEqual([x.text for x in w], toks)
        self.assertAlmostEqual(w[-1].end, 1.6)

    def test_merge_split_word(self):
        w = _merge_to_tokens(["supermarket."], [("super", 0.0, 0.3), ("market", 0.3, 0.7)], 1.0)
        self.assertEqual(len(w), 1)
        self.assertAlmostEqual(w[0].end, 0.7)


class TestSchema(unittest.TestCase):
    def test_unknown_speaker_rejected(self):
        with self.assertRaises(Exception):
            Screenplay.model_validate({"title": "x", "scenes": [{"id": "s", "shots": [
                {"line": {"speaker": "ghost", "text": "boo"}}]}]})

    def test_camera_from_alias(self):
        sp = Screenplay.model_validate({"title": "x", "scenes": [{"id": "s", "shots": [
            {"camera": {"type": "zoom_in", "from": 1.0, "to": 1.2}, "duration": 1}]}]})
        self.assertEqual(sp.scenes[0].shots[0].camera.to, 1.2)


class TestCaptions(unittest.TestCase):
    def test_pages_no_overlap_and_highlight(self):
        style = load_style("miniseries")
        ct = CaptionTrack(style, 1080, 1920)
        words = [("Then", 0.1, 0.3), ("his", 0.3, 0.5), ("phone", 0.5, 0.8), ("rings.", 0.8, 1.1),
                 ("It's", 1.4, 1.6), ("mom.", 1.6, 2.0)]
        ct.add_line(words, ["mom"], 2.0, 3.0)
        self.assertEqual([[w.display for w in p.words] for p in ct.pages],
                         [["THEN", "HIS", "PHONE"], ["RINGS"], ["IT'S", "MOM"]])
        for a, b in zip(ct.pages, ct.pages[1:]):
            self.assertLessEqual(a.end, b.start + 1e-9)
        self.assertTrue(ct.pages[-1].words[-1].highlight)


if __name__ == "__main__":
    unittest.main()
