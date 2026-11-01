"""Run: python -m unittest discover tests"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.compose import post_text  # noqa: E402
from engine.config import ROOT  # noqa: E402
from engine.schema import Screenplay  # noqa: E402
from scripts.check_output import parse_srt  # noqa: E402
from scripts.preview import _circle_rect  # noqa: E402
from scripts.validate import validate  # noqa: E402

BASE = json.loads((ROOT / "projects" / "phase4-test" / "screenplay.json").read_text())


def project_with(mutate) -> Path:
    d = Path(tempfile.mkdtemp())
    data = json.loads(json.dumps(BASE))
    mutate(data)
    (d / "screenplay.json").write_text(json.dumps(data))
    return d


class TestValidate(unittest.TestCase):
    def test_example_projects_have_no_errors(self):
        for p in ("phase1-test", "phase2-test", "phase3-test", "phase4-test"):
            self.assertEqual(validate(ROOT / "projects" / p).errors, [], p)

    def test_catches_bad_references(self):
        def bad(d):
            sh = d["scenes"][1]["shots"]
            sh[0]["camera"]["target"] = "courier.nose"
            sh[0]["actors"][0]["pose"] = "dance"
            sh[1]["poll"] = [3]
            sh[1]["sfx"] = [{"name": "laser"}]
            sh[1]["props"] = [{"svg": "sword"}, {"svg": "phone", "attach_to": "ghost.hand_r"}]
            d["scenes"][0]["background"] = "moon_base"
        d = project_with(bad)
        try:
            errs = "\n".join(validate(d).errors)
        finally:
            shutil.rmtree(d)
        for needle in ("nose", "dance", "poll option 3", "laser", "sword", "ghost", "moon_base"):
            self.assertIn(needle, errs)

    def test_schema_error_reported(self):
        d = project_with(lambda x: x["scenes"][0].pop("id"))
        try:
            self.assertTrue(any("schema" in e for e in validate(d).errors))
        finally:
            shutil.rmtree(d)


class TestHelpers(unittest.TestCase):
    def test_post_text_uses_post_field(self):
        sp = Screenplay.model_validate({**BASE, "post": {"caption": "Would you answer?", "hashtags": ["zombie", "#story"]}})
        self.assertEqual(post_text(sp), "Would you answer?\n\n#zombie #story\n")

    def test_post_text_fallback(self):
        txt = post_text(Screenplay.model_validate(BASE))
        self.assertIn("Ep 13", txt)
        self.assertIn("1) Call her back", txt)

    def test_srt_parse(self):
        s = parse_srt("1\n00:00:01,500 --> 00:00:02,000\nHELLO\n\n2\n00:00:02,000 --> 00:00:03,250\nWORLD\n")
        self.assertEqual(s, [(1.5, 2.0, "HELLO"), (2.0, 3.25, "WORLD")])

    def test_circle_rect_overlap(self):
        self.assertGreater(_circle_rect(50, 50, 20, (40, 40, 100, 100)), 0.9)
        self.assertEqual(_circle_rect(0, 0, 10, (40, 40, 100, 100)), 0.0)


if __name__ == "__main__":
    unittest.main()
