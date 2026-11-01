"""Run: python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import skia  # noqa: E402

from engine.camera import camera_matrix, camera_zoom, resolve_target  # noqa: E402
from engine.config import ROOT, load_style  # noqa: E402
from engine.lighting import draw_lighting  # noqa: E402
from engine.props import PropLibrary, prop_motion  # noqa: E402
from engine.schema import Camera, Lighting  # noqa: E402

W, H = 1080, 1920


class TestCamera(unittest.TestCase):
    def setUp(self):
        self.style = load_style("dark_miniseries")

    def test_zoom_never_below_one_and_eases(self):
        cam = Camera.model_validate({"type": "zoom_in", "from": 0.5, "to": 2.0})
        self.assertEqual(camera_zoom(cam, 0, 2), 1.0)
        self.assertAlmostEqual(camera_zoom(cam, 2, 2), 2.0)

    def test_view_stays_inside_world(self):
        cam = Camera.model_validate({"from": 2.0, "target": "a"})
        m = camera_matrix(cam, 0.5, 2, W, H, {"a": {"head": (5, 5)}}, self.style)
        tl = m.mapXY(0, 0)   # world corner must not appear inside the screen
        self.assertLessEqual(tl.x(), 0.01)
        self.assertLessEqual(tl.y(), 0.01)

    def test_target_lands_at_frame_y(self):
        cam = Camera.model_validate({"from": 2.0, "target": "a.head", "frame_y": 0.4})
        m = camera_matrix(cam, 0.0, 2, W, H, {"a": {"head": (540, 900)}}, self.style)
        p = m.mapXY(540, 900)
        self.assertAlmostEqual(p.x(), W / 2, delta=1)
        self.assertAlmostEqual(p.y(), 0.4 * H, delta=1)

    def test_resolve_target_default_part(self):
        self.assertEqual(resolve_target("a", {"a": {"head": (1, 2), "chest": (3, 4)}}), (1, 2))
        self.assertEqual(resolve_target("p", {"p": {"center": (7, 8)}}), (7, 8))
        self.assertIsNone(resolve_target("missing", {}))


class TestProps(unittest.TestCase):
    def test_all_library_props_render(self):
        lib = PropLibrary(load_style("miniseries"))
        for svg in sorted((ROOT / "library" / "props").glob("*.svg")):
            img = lib.image(svg.stem, {"text": "hello world"}, 200)
            self.assertGreater(img.width(), 0, svg.stem)

    def test_text_fits_available_lines(self):
        lib = PropLibrary(load_style("miniseries"))
        svg = lib.render_svg("cardboard_sign", {"text": "a " * 40}, 300)
        self.assertNotIn("{{", svg)

    def test_motions(self):
        for a in ("ring", "bob", "pulse", "swing", "pop", "drop", None):
            rot, dy, s = prop_motion(a, 0.1)
            self.assertGreater(s, 0)


class TestLighting(unittest.TestCase):
    def test_cone_lights_inside_and_darkens_outside(self):
        L = Lighting.model_validate({"darkness": 0.8, "lights": [{"type": "cone", "x": 0.2, "y": 0.5,
                                                                    "angle": 0, "radius": 0.5}]})
        s = skia.Surface(W, H)
        c = s.getCanvas()
        c.clear(skia.Color(120, 120, 120))
        draw_lighting(c, L, {}, W, H, 0.0, load_style("miniseries"))
        a = s.makeImageSnapshot().toarray()
        self.assertGreater(int(a[960, 600, :3].mean()), int(a[300, 900, :3].mean()) + 40)


if __name__ == "__main__":
    unittest.main()
