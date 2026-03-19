"""Tests for atlas packing behavior."""

import os
import shutil
import tempfile
import unittest

from PIL import Image

from actool.compiler import compile_catalog
from tests.helpers import make_temp_catalog, parse_car_layouts


class TestSingleFormatInline(unittest.TestCase):
    """Single image of a given format should be stored inline."""

    def test_lone_ga8_inline(self):
        """3 BGRA + 1 LA → LA is inline (only GA8 image)."""
        tmpdir = tempfile.mkdtemp()
        try:
            catalog, _ = make_temp_catalog(
                [("A", "RGBA"), ("B", "RGBA"), ("C", "RGBA"), ("Mono", "LA")],
                tmpdir)
            outdir = os.path.join(tmpdir, "out")
            compile_catalog(catalog, outdir, "macosx", "11.0")
            layouts = parse_car_layouts(os.path.join(outdir, "Assets.car"))
            self.assertEqual(layouts["Mono.png"], 12)
            self.assertEqual(layouts["Mono@2x.png"], 12)
            self.assertEqual(layouts["A.png"], 1003)
        finally:
            shutil.rmtree(tmpdir)

    def test_all_same_format_packed(self):
        """3 LA images → all packed."""
        tmpdir = tempfile.mkdtemp()
        try:
            catalog, _ = make_temp_catalog(
                [("X", "LA"), ("Y", "LA"), ("Z", "LA")], tmpdir)
            outdir = os.path.join(tmpdir, "out")
            compile_catalog(catalog, outdir, "macosx", "11.0")
            layouts = parse_car_layouts(os.path.join(outdir, "Assets.car"))
            for name in ["X.png", "Y.png", "Z.png"]:
                self.assertEqual(layouts[name], 1003)
        finally:
            shutil.rmtree(tmpdir)

    def test_single_imageset_inline(self):
        """Single imageset → stored inline, no atlas."""
        tmpdir = tempfile.mkdtemp()
        try:
            catalog, _ = make_temp_catalog([("Solo", "RGBA")], tmpdir)
            outdir = os.path.join(tmpdir, "out")
            compile_catalog(catalog, outdir, "macosx", "11.0")
            layouts = parse_car_layouts(os.path.join(outdir, "Assets.car"))
            self.assertEqual(layouts["Solo.png"], 12)
            self.assertFalse(any(n.startswith("ZZZZ") for n in layouts))
        finally:
            shutil.rmtree(tmpdir)

    def test_two_formats_one_each_both_inline(self):
        """1 RGBA + 1 LA → both inline."""
        tmpdir = tempfile.mkdtemp()
        try:
            catalog, _ = make_temp_catalog(
                [("Color", "RGBA"), ("Gray", "LA")], tmpdir)
            outdir = os.path.join(tmpdir, "out")
            compile_catalog(catalog, outdir, "macosx", "11.0")
            layouts = parse_car_layouts(os.path.join(outdir, "Assets.car"))
            self.assertEqual(layouts["Color.png"], 12)
            self.assertEqual(layouts["Gray.png"], 12)
        finally:
            shutil.rmtree(tmpdir)


class TestGrayscaleDetection(unittest.TestCase):
    """RGBA images with R==G==B should be detected as GA8."""

    def test_white_rgba_detected_as_ga8(self):
        """White RGBA (R==G==B) becomes GA8 → stored inline when lone GA8."""
        tmpdir = tempfile.mkdtemp()
        try:
            catalog = os.path.join(tmpdir, "Test.xcassets")
            os.makedirs(catalog)
            with open(os.path.join(catalog, "Contents.json"), "w") as f:
                f.write('{"info":{"author":"xcode","version":1}}')

            for name, color in [("Red", (255, 0, 0, 255)),
                                ("Blue", (0, 0, 255, 255))]:
                iset = os.path.join(catalog, f"{name}.imageset")
                os.makedirs(iset)
                Image.new("RGBA", (16, 16), color).save(
                    os.path.join(iset, f"{name}.png"))
                Image.new("RGBA", (32, 32), color).save(
                    os.path.join(iset, f"{name}@2x.png"))
                import json
                with open(os.path.join(iset, "Contents.json"), "w") as f:
                    json.dump({"images": [
                        {"filename": f"{name}.png", "idiom": "mac",
                         "scale": "1x"},
                        {"filename": f"{name}@2x.png", "idiom": "mac",
                         "scale": "2x"},
                    ], "info": {"author": "xcode", "version": 1}}, f)

            # White (R==G==B) RGBA image
            iset = os.path.join(catalog, "White.imageset")
            os.makedirs(iset)
            Image.new("RGBA", (16, 16), (255, 255, 255, 255)).save(
                os.path.join(iset, "White.png"))
            Image.new("RGBA", (32, 32), (255, 255, 255, 255)).save(
                os.path.join(iset, "White@2x.png"))
            import json
            with open(os.path.join(iset, "Contents.json"), "w") as f:
                json.dump({"images": [
                    {"filename": "White.png", "idiom": "mac", "scale": "1x"},
                    {"filename": "White@2x.png", "idiom": "mac",
                     "scale": "2x"},
                ], "info": {"author": "xcode", "version": 1}}, f)

            outdir = os.path.join(tmpdir, "out")
            compile_catalog(catalog, outdir, "macosx", "11.0")
            layouts = parse_car_layouts(os.path.join(outdir, "Assets.car"))

            self.assertEqual(layouts["White.png"], 12, "White should be inline")
            self.assertEqual(layouts["Red.png"], 1003, "Red should be packed")
        finally:
            shutil.rmtree(tmpdir)


if __name__ == "__main__":
    unittest.main()
