"""Tests using assetutil to validate CAR files.

Skipped when /usr/bin/assetutil is not available.
"""

import os
import shutil
import unittest

from actool.compiler import compile_catalog
from tests.helpers import (
    REF_XCASSETS, has_assetutil, run_assetutil,
    make_temp_catalog, get_test_outdir, cleanup_test_outputs,
)


@unittest.skipUnless(has_assetutil(), "assetutil not available")
class TestAssetutilValidation(unittest.TestCase):
    """Validate that assetutil can read our CAR files."""

    @classmethod
    def tearDownClass(cls):
        cleanup_test_outputs()

    def test_main_catalog(self):
        """Full Images.xcassets with app icon."""
        outdir = get_test_outdir("main")
        compile_catalog(REF_XCASSETS, outdir, "macosx", "11.0",
                        app_icon="AppIcon",
                        info_plist_path=os.path.join(outdir, "Info.plist"))
        result = run_assetutil(os.path.join(outdir, "Assets.car"))
        self.assertIsNotNone(result, "assetutil returned no output")
        self.assertEqual(len(result), 63)  # 1 header + 62 renditions

    def test_asset_types(self):
        """Check asset type counts match expectations."""
        outdir = get_test_outdir("types")
        compile_catalog(REF_XCASSETS, outdir, "macosx", "11.0",
                        app_icon="AppIcon",
                        info_plist_path=os.path.join(outdir, "Info.plist"))
        result = run_assetutil(os.path.join(outdir, "Assets.car"))
        self.assertIsNotNone(result)

        types = {}
        for entry in result[1:]:
            t = entry.get("AssetType", "?")
            types[t] = types.get(t, 0) + 1

        self.assertEqual(types.get("Icon Image", 0), 10)
        self.assertEqual(types.get("Image", 0), 42)
        self.assertEqual(types.get("MultiSized Image", 0), 1)
        self.assertEqual(types.get("PackedImage", 0), 7)

    def test_no_icon_catalog(self):
        """Catalog without app icon."""
        outdir = get_test_outdir("noicon")
        compile_catalog(REF_XCASSETS, outdir, "macosx", "11.0")
        result = run_assetutil(os.path.join(outdir, "Assets.car"))
        self.assertIsNotNone(result, "assetutil returned no output")
        self.assertGreater(len(result), 1)

    def test_simple_catalog(self):
        """Minimal catalog with 2 imagesets."""
        catalog, tmpdir = make_temp_catalog(
            [("A", "RGBA"), ("B", "RGBA")])
        try:
            outdir = get_test_outdir("simple")
            compile_catalog(catalog, outdir, "macosx", "11.0")
            result = run_assetutil(os.path.join(outdir, "Assets.car"))
            self.assertIsNotNone(result, "assetutil returned no output")
        finally:
            shutil.rmtree(tmpdir)

    def test_single_imageset(self):
        """Single imageset (no packing)."""
        catalog, tmpdir = make_temp_catalog([("Solo", "RGBA")])
        try:
            outdir = get_test_outdir("single")
            compile_catalog(catalog, outdir, "macosx", "11.0")
            result = run_assetutil(os.path.join(outdir, "Assets.car"))
            self.assertIsNotNone(result)
        finally:
            shutil.rmtree(tmpdir)

    def test_mixed_formats(self):
        """Mixed BGRA + GA8 formats."""
        catalog, tmpdir = make_temp_catalog(
            [("A", "RGBA"), ("B", "RGBA"), ("C", "LA")])
        try:
            outdir = get_test_outdir("mixed")
            compile_catalog(catalog, outdir, "macosx", "11.0")
            result = run_assetutil(os.path.join(outdir, "Assets.car"))
            self.assertIsNotNone(result)
        finally:
            shutil.rmtree(tmpdir)


if __name__ == "__main__":
    unittest.main()
