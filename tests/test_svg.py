"""Tests for SVG support in imagesets, appiconsets, and .icon bundles."""

import json
import os
import platform
import shutil
import struct
import sys
import tempfile
import unittest

from actool import car
from actool.catalog import _bgra_to_best_format
from actool.compiler import compile_catalog
from actool.svg_raster import HAS_CORESVG
from tests.helpers import (
    has_assetutil, has_system_actool,
    parse_car_csi_by_name, parse_car_info,
    compile_with_system_actool, run_assetutil,
)

SIMPLE_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"'
    b' viewBox="0 0 64 64">'
    b'<circle cx="32" cy="32" r="30" fill="#FF0000"/>'
    b'</svg>'
)

GRAY_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"'
    b' viewBox="0 0 64 64">'
    b'<circle cx="32" cy="32" r="30" fill="#808080"/>'
    b'</svg>'
)

IS_MACOS = sys.platform == "darwin"


def _make_svg_imageset_catalog(tmpdir, svg_data=SIMPLE_SVG):
    """Create an xcassets catalog with one SVG imageset."""
    catalog = os.path.join(tmpdir, "Test.xcassets")
    os.makedirs(catalog, exist_ok=True)
    with open(os.path.join(catalog, "Contents.json"), "w") as f:
        json.dump({"info": {"author": "xcode", "version": 1}}, f)

    iset = os.path.join(catalog, "TestSVG.imageset")
    os.makedirs(iset)
    with open(os.path.join(iset, "icon.svg"), "wb") as f:
        f.write(svg_data)
    with open(os.path.join(iset, "Contents.json"), "w") as f:
        json.dump({
            "images": [{"filename": "icon.svg", "idiom": "universal"}],
            "info": {"author": "xcode", "version": 1},
        }, f)
    return catalog


def _make_svg_appiconset_catalog(tmpdir, svg_data=SIMPLE_SVG):
    """Create an xcassets catalog with a mixed SVG+PNG appiconset."""
    from PIL import Image

    catalog = os.path.join(tmpdir, "Test.xcassets")
    os.makedirs(catalog, exist_ok=True)
    with open(os.path.join(catalog, "Contents.json"), "w") as f:
        json.dump({"info": {"author": "xcode", "version": 1}}, f)

    iconset = os.path.join(catalog, "AppIcon.appiconset")
    os.makedirs(iconset)
    with open(os.path.join(iconset, "icon.svg"), "wb") as f:
        f.write(svg_data)
    Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(
        os.path.join(iconset, "icon_32.png"))
    with open(os.path.join(iconset, "Contents.json"), "w") as f:
        json.dump({
            "images": [
                {"filename": "icon.svg", "idiom": "mac",
                 "size": "64x64", "scale": "1x"},
                {"filename": "icon_32.png", "idiom": "mac",
                 "size": "32x32", "scale": "1x"},
            ],
            "info": {"author": "xcode", "version": 1},
        }, f)
    return catalog


def _make_icon_bundle(tmpdir, svg_data_list=None):
    """Create a .icon bundle with SVG layers."""
    if svg_data_list is None:
        svg_data_list = [SIMPLE_SVG, GRAY_SVG]

    bundle = os.path.join(tmpdir, "TestIcon.icon")
    assets = os.path.join(bundle, "Assets")
    os.makedirs(assets)

    layers = []
    for i, svg_data in enumerate(svg_data_list, 1):
        name = f"{i}.svg"
        with open(os.path.join(assets, name), "wb") as f:
            f.write(svg_data)
        layers.append({"image-name": name, "name": str(i)})

    icon_json = {
        "groups": [{"layers": layers}],
        "supported-platforms": {"squares": "shared"},
    }
    with open(os.path.join(bundle, "icon.json"), "w") as f:
        json.dump(icon_json, f)
    return bundle


# ---------------------------------------------------------------------------
# Unit tests (platform-independent)
# ---------------------------------------------------------------------------

class TestBuildSvgCsi(unittest.TestCase):
    """Unit tests for car.build_svg_csi."""

    def test_csi_header_fields(self):
        csi = car.build_svg_csi("test.svg", b"<svg/>")
        self.assertEqual(csi[:4], b"ISTC")
        pf = csi[24:28]
        self.assertEqual(pf, car.PIXELFMT_SVG)
        layout = struct.unpack_from("<H", csi, 36)[0]
        self.assertEqual(layout, car.LAYOUT_PDF)
        flags = struct.unpack_from("<I", csi, 8)[0]
        self.assertEqual(flags, 0x04)

    def test_csi_contains_name(self):
        csi = car.build_svg_csi("hello.svg", b"<svg/>")
        name = csi[40:168].split(b'\x00')[0]
        self.assertEqual(name, b"hello.svg")

    def test_rawd_wraps_data(self):
        svg = b"<svg>content</svg>"
        csi = car.build_svg_csi("t.svg", svg)
        rawd_pos = csi.find(b"DWAR")
        self.assertGreater(rawd_pos, 0)
        unk = struct.unpack_from("<I", csi, rawd_pos + 4)[0]
        length = struct.unpack_from("<I", csi, rawd_pos + 8)[0]
        payload = csi[rawd_pos + 12:rawd_pos + 12 + length]
        if car.HAS_LZFSE:
            if unk == 1:
                import liblzfse
                decompressed = liblzfse.decompress(payload)
                self.assertEqual(decompressed, svg)
            else:
                self.assertEqual(unk, 0)
                self.assertEqual(payload, svg)
        else:
            self.assertEqual(payload, svg)

    def test_rawd_compresses_when_beneficial(self):
        # Large enough SVG that compression helps
        svg = b'<svg>' + b'<circle r="10"/>' * 50 + b'</svg>'
        csi = car.build_svg_csi("big.svg", svg)
        rawd_pos = csi.find(b"DWAR")
        unk = struct.unpack_from("<I", csi, rawd_pos + 4)[0]
        length = struct.unpack_from("<I", csi, rawd_pos + 8)[0]
        if car.HAS_LZFSE:
            self.assertEqual(unk, 1)
            self.assertLess(length, len(svg))

    def test_rawd_skips_compression_when_larger(self):
        # Tiny SVG where compression doesn't help
        svg = b"<svg/>"
        csi = car.build_svg_csi("tiny.svg", svg)
        rawd_pos = csi.find(b"DWAR")
        unk = struct.unpack_from("<I", csi, rawd_pos + 4)[0]
        length = struct.unpack_from("<I", csi, rawd_pos + 8)[0]
        payload = csi[rawd_pos + 12:rawd_pos + 12 + length]
        self.assertEqual(unk, 0)
        self.assertEqual(payload, svg)

    def test_pixelfmt_svg_constant(self):
        self.assertEqual(car.PIXELFMT_SVG, b" GVS")


class TestBgraTobestFormat(unittest.TestCase):
    """Unit tests for _bgra_to_best_format."""

    def test_grayscale_detected(self):
        # BGRA where B==G==R for every pixel
        bgra = bytes([100, 100, 100, 255] * 4)
        data, w, h, fmt = _bgra_to_best_format(bgra, 2, 2)
        self.assertEqual(fmt, b" 8AG")
        self.assertEqual(len(data), 2 * 2 * 2)

    def test_color_stays_bgra(self):
        bgra = bytes([100, 200, 50, 255] * 4)
        data, w, h, fmt = _bgra_to_best_format(bgra, 2, 2)
        self.assertEqual(fmt, b"BGRA")
        self.assertEqual(data, bgra)

    def test_force_bgra_overrides_gray(self):
        bgra = bytes([100, 100, 100, 255] * 4)
        data, w, h, fmt = _bgra_to_best_format(bgra, 2, 2, force_bgra=True)
        self.assertEqual(fmt, b"BGRA")

    def test_ga8_values_correct(self):
        bgra = bytes([50, 50, 50, 128, 200, 200, 200, 255])
        data, w, h, fmt = _bgra_to_best_format(bgra, 2, 1)
        self.assertEqual(fmt, b" 8AG")
        # GA8: [gray, alpha] pairs
        self.assertEqual(data[0], 50)
        self.assertEqual(data[1], 128)
        self.assertEqual(data[2], 200)
        self.assertEqual(data[3], 255)


class TestSvgDimensionParsing(unittest.TestCase):
    """Unit tests for SVG dimension extraction."""

    def test_width_height_attrs(self):
        from actool.svg_raster import _parse_svg_dimensions
        svg = b'<svg width="128" height="64" viewBox="0 0 128 64"></svg>'
        w, h = _parse_svg_dimensions(svg)
        self.assertEqual(w, 128)
        self.assertEqual(h, 64)

    def test_viewbox_fallback(self):
        from actool.svg_raster import _parse_svg_dimensions
        svg = b'<svg viewBox="0 0 200 100"></svg>'
        w, h = _parse_svg_dimensions(svg)
        self.assertEqual(w, 200)
        self.assertEqual(h, 100)

    def test_no_dimensions(self):
        from actool.svg_raster import _parse_svg_dimensions
        svg = b'<svg><circle r="10"/></svg>'
        w, h = _parse_svg_dimensions(svg)
        self.assertEqual(w, 0)
        self.assertEqual(h, 0)

    def test_float_dimensions(self):
        from actool.svg_raster import _parse_svg_dimensions
        svg = b'<svg width="64.5" height="32.7"></svg>'
        w, h = _parse_svg_dimensions(svg)
        self.assertEqual(w, 64)
        self.assertEqual(h, 32)


class TestSvgRenditionFlags(unittest.TestCase):
    """Rasterized SVG renditions must have the 0x04 flag set."""

    def test_svg_rasterization_flag(self):
        rend = car.Rendition(
            name="test.svg", identifier=1,
            width=64, height=64,
            pixel_data=b"\x00" * (64 * 64 * 4),
            pixel_format=b"BGRA",
            template_rendering_intent=0,
            is_svg_rasterization=True,
        )
        csi = rend.build_csi()
        flags = struct.unpack_from("<I", csi, 8)[0]
        self.assertEqual(flags & 0x04, 0x04)

    def test_non_svg_no_flag(self):
        rend = car.Rendition(
            name="test.png", identifier=1,
            width=64, height=64,
            pixel_data=b"\x00" * (64 * 64 * 4),
            pixel_format=b"BGRA",
            template_rendering_intent=0,
            is_svg_rasterization=False,
        )
        csi = rend.build_csi()
        flags = struct.unpack_from("<I", csi, 8)[0]
        self.assertEqual(flags & 0x04, 0)

    def test_automatic_intent_plus_svg_flag(self):
        rend = car.Rendition(
            name="test.svg", identifier=1,
            width=64, height=64,
            pixel_data=b"\x00" * (64 * 64 * 4),
            pixel_format=b"BGRA",
            template_rendering_intent=4,
            is_svg_rasterization=True,
        )
        csi = rend.build_csi()
        flags = struct.unpack_from("<I", csi, 8)[0]
        # intent=4 → 0x10, plus SVG flag 0x04 → 0x14
        self.assertEqual(flags, 0x14)


# ---------------------------------------------------------------------------
# Integration tests — SVG imageset compilation
# ---------------------------------------------------------------------------

class TestSvgImagesetCompilation(unittest.TestCase):
    """SVG files in imagesets produce vector + rasterized renditions."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="actool_svg_test_")
        self.outdir = os.path.join(self.tmpdir, "out")
        os.makedirs(self.outdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_svg_imageset_produces_car(self):
        catalog = _make_svg_imageset_catalog(self.tmpdir)
        output = compile_catalog(catalog, self.outdir, "macosx", "11.0")
        car_path = os.path.join(self.outdir, "Assets.car")
        self.assertTrue(os.path.exists(car_path))
        self.assertIn(os.path.abspath(car_path), output)

    def test_svg_imageset_has_vector_rendition(self):
        catalog = _make_svg_imageset_catalog(self.tmpdir)
        compile_catalog(catalog, self.outdir, "macosx", "11.0")
        car_path = os.path.join(self.outdir, "Assets.car")
        csis = parse_car_csi_by_name(car_path)
        svg_entries = csis.get("icon.svg", [])

        vector_entries = [e for e in svg_entries
                          if e["layout"] == car.LAYOUT_PDF]
        self.assertEqual(len(vector_entries), 1)
        self.assertEqual(vector_entries[0]["pixel_format"], car.PIXELFMT_SVG)
        self.assertEqual(vector_entries[0]["flags"], 0x04)

    def test_svg_imageset_rawd_stores_svg_data(self):
        catalog = _make_svg_imageset_catalog(self.tmpdir)
        compile_catalog(catalog, self.outdir, "macosx", "11.0")
        car_path = os.path.join(self.outdir, "Assets.car")
        csis = parse_car_csi_by_name(car_path)
        svg_entries = csis.get("icon.svg", [])

        vector_entry = [e for e in svg_entries
                        if e["layout"] == car.LAYOUT_PDF][0]
        rawd = vector_entry["rend"]
        self.assertEqual(rawd[:4], b"DWAR")
        unk = struct.unpack_from("<I", rawd, 4)[0]
        self.assertIn(unk, (0, 1))
        length = struct.unpack_from("<I", rawd, 8)[0]
        self.assertGreater(length, 0)

    @unittest.skipUnless(HAS_CORESVG, "CoreSVG not available (macOS only)")
    def test_svg_imageset_has_rasterized_renditions(self):
        catalog = _make_svg_imageset_catalog(self.tmpdir)
        compile_catalog(catalog, self.outdir, "macosx", "11.0")
        car_path = os.path.join(self.outdir, "Assets.car")
        csis = parse_car_csi_by_name(car_path)
        svg_entries = csis.get("icon.svg", [])

        raster_entries = [e for e in svg_entries
                          if e["layout"] == car.LAYOUT_ONE_PART_SCALE]
        self.assertEqual(len(raster_entries), 2)
        scales = sorted(e["scale"] for e in raster_entries)
        self.assertEqual(scales, [1, 2])

    @unittest.skipUnless(HAS_CORESVG, "CoreSVG not available (macOS only)")
    def test_svg_imageset_raster_dimensions(self):
        catalog = _make_svg_imageset_catalog(self.tmpdir)
        compile_catalog(catalog, self.outdir, "macosx", "11.0")
        car_path = os.path.join(self.outdir, "Assets.car")
        csis = parse_car_csi_by_name(car_path)
        svg_entries = csis.get("icon.svg", [])

        for entry in svg_entries:
            if entry["layout"] != car.LAYOUT_ONE_PART_SCALE:
                continue
            scale = entry["scale"]
            self.assertEqual(entry["width"], 64 * scale)
            self.assertEqual(entry["height"], 64 * scale)

    @unittest.skipUnless(HAS_CORESVG, "CoreSVG not available (macOS only)")
    def test_svg_imageset_raster_flags(self):
        """Rasterized SVG images in imagesets have flags 0x14 (intent=4 + svg)."""
        catalog = _make_svg_imageset_catalog(self.tmpdir)
        compile_catalog(catalog, self.outdir, "macosx", "11.0")
        car_path = os.path.join(self.outdir, "Assets.car")
        csis = parse_car_csi_by_name(car_path)
        svg_entries = csis.get("icon.svg", [])

        for entry in svg_entries:
            if entry["layout"] == car.LAYOUT_ONE_PART_SCALE:
                self.assertEqual(entry["flags"], 0x14)


# ---------------------------------------------------------------------------
# Integration tests — SVG in appiconset
# ---------------------------------------------------------------------------

class TestSvgAppiconsetCompilation(unittest.TestCase):
    """SVG files in appiconsets produce vector + rasterized + multisize."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="actool_svg_icon_test_")
        self.outdir = os.path.join(self.tmpdir, "out")
        os.makedirs(self.outdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_mixed_svg_png_produces_car(self):
        catalog = _make_svg_appiconset_catalog(self.tmpdir)
        output = compile_catalog(
            catalog, self.outdir, "macosx", "11.0", app_icon="AppIcon")
        car_path = os.path.join(self.outdir, "Assets.car")
        self.assertTrue(os.path.exists(car_path))

    def test_svg_vector_rendition_in_icon(self):
        catalog = _make_svg_appiconset_catalog(self.tmpdir)
        compile_catalog(
            catalog, self.outdir, "macosx", "11.0", app_icon="AppIcon")
        car_path = os.path.join(self.outdir, "Assets.car")
        csis = parse_car_csi_by_name(car_path)
        svg_entries = csis.get("icon.svg", [])

        vector = [e for e in svg_entries if e["layout"] == car.LAYOUT_PDF]
        self.assertEqual(len(vector), 1)
        self.assertEqual(vector[0]["pixel_format"], car.PIXELFMT_SVG)

    @unittest.skipUnless(HAS_CORESVG, "CoreSVG not available (macOS only)")
    def test_svg_rasterized_at_1x_and_2x(self):
        catalog = _make_svg_appiconset_catalog(self.tmpdir)
        compile_catalog(
            catalog, self.outdir, "macosx", "11.0", app_icon="AppIcon")
        car_path = os.path.join(self.outdir, "Assets.car")
        csis = parse_car_csi_by_name(car_path)
        svg_entries = csis.get("icon.svg", [])

        raster = [e for e in svg_entries
                   if e["layout"] == car.LAYOUT_ONE_PART_SCALE]
        self.assertEqual(len(raster), 2)
        scales = sorted(e["scale"] for e in raster)
        self.assertEqual(scales, [1, 2])

    @unittest.skipUnless(HAS_CORESVG, "CoreSVG not available (macOS only)")
    def test_svg_icon_raster_flags(self):
        """Rasterized SVG in icon uses flags 0x04 (intent=0 + svg flag)."""
        catalog = _make_svg_appiconset_catalog(self.tmpdir)
        compile_catalog(
            catalog, self.outdir, "macosx", "11.0", app_icon="AppIcon")
        car_path = os.path.join(self.outdir, "Assets.car")
        csis = parse_car_csi_by_name(car_path)
        svg_entries = csis.get("icon.svg", [])

        for entry in svg_entries:
            if entry["layout"] == car.LAYOUT_ONE_PART_SCALE:
                self.assertEqual(entry["flags"], 0x04)

    def test_png_alongside_svg_unaffected(self):
        catalog = _make_svg_appiconset_catalog(self.tmpdir)
        compile_catalog(
            catalog, self.outdir, "macosx", "11.0", app_icon="AppIcon")
        car_path = os.path.join(self.outdir, "Assets.car")
        csis = parse_car_csi_by_name(car_path)

        png_entries = csis.get("icon_32.png", [])
        self.assertEqual(len(png_entries), 1)
        self.assertEqual(png_entries[0]["layout"], car.LAYOUT_ONE_PART_SCALE)
        self.assertEqual(png_entries[0]["pixel_format"], b"BGRA")
        self.assertEqual(png_entries[0]["width"], 32)

    def test_multisize_rendition_present(self):
        catalog = _make_svg_appiconset_catalog(self.tmpdir)
        compile_catalog(
            catalog, self.outdir, "macosx", "11.0", app_icon="AppIcon")
        car_path = os.path.join(self.outdir, "Assets.car")
        csis = parse_car_csi_by_name(car_path)

        ms_entries = csis.get("AppIcon", [])
        ms = [e for e in ms_entries
              if e["layout"] == car.LAYOUT_MULTISIZE_IMAGE]
        self.assertEqual(len(ms), 1)

    def test_icns_skips_svg(self):
        """ICNS generation must skip SVG files (not crash)."""
        from actool.catalog import AssetCatalog
        catalog = _make_svg_appiconset_catalog(self.tmpdir)
        cat = AssetCatalog(catalog, platform="macosx", min_deploy="11.0",
                           app_icon="AppIcon")
        icon_images = cat.get_icon_images()
        for path, _, _ in icon_images:
            self.assertFalse(path.endswith(".svg"),
                             f"SVG should not be in ICNS image list: {path}")


# ---------------------------------------------------------------------------
# Integration tests — .icon bundle
# ---------------------------------------------------------------------------

class TestIconBundleCompilation(unittest.TestCase):
    """SVG-based .icon bundles store each layer as raw vector data."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="actool_icon_bundle_test_")
        self.outdir = os.path.join(self.tmpdir, "out")
        os.makedirs(self.outdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_icon_bundle_produces_car(self):
        bundle = _make_icon_bundle(self.tmpdir)
        from actool.icon_bundle import compile_icon_bundle
        output = compile_icon_bundle(
            bundle, self.outdir, "macosx", "26.0",
            app_icon="TestIcon",
            info_plist_path=os.path.join(self.outdir, "info.plist"))
        car_path = os.path.join(self.outdir, "Assets.car")
        self.assertTrue(os.path.exists(car_path))

    def test_icon_bundle_all_layers_stored(self):
        svgs = [SIMPLE_SVG, GRAY_SVG, SIMPLE_SVG]
        bundle = _make_icon_bundle(self.tmpdir, svgs)
        from actool.icon_bundle import compile_icon_bundle
        compile_icon_bundle(
            bundle, self.outdir, "macosx", "26.0", app_icon="TestIcon")
        car_path = os.path.join(self.outdir, "Assets.car")
        csis = parse_car_csi_by_name(car_path)

        svg_names = set()
        for name, entries in csis.items():
            for e in entries:
                if e["pixel_format"] == car.PIXELFMT_SVG:
                    svg_names.add(name)
        self.assertEqual(len(svg_names), 3)

    def test_icon_bundle_layers_have_distinct_keys(self):
        svgs = [SIMPLE_SVG, GRAY_SVG]
        bundle = _make_icon_bundle(self.tmpdir, svgs)
        from actool.icon_bundle import compile_icon_bundle
        compile_icon_bundle(
            bundle, self.outdir, "macosx", "26.0", app_icon="TestIcon")
        car_path = os.path.join(self.outdir, "Assets.car")
        info = parse_car_info(car_path)
        # 2 SVG layers → 2 renditions (distinct keys)
        self.assertEqual(info["rendition_count"], 2)

    def test_icon_bundle_svg_stored_in_rawd(self):
        bundle = _make_icon_bundle(self.tmpdir, [SIMPLE_SVG])
        from actool.icon_bundle import compile_icon_bundle
        compile_icon_bundle(
            bundle, self.outdir, "macosx", "26.0", app_icon="TestIcon")
        car_path = os.path.join(self.outdir, "Assets.car")
        csis = parse_car_csi_by_name(car_path)

        for name, entries in csis.items():
            for e in entries:
                if e["pixel_format"] != car.PIXELFMT_SVG:
                    continue
                rawd = e["rend"]
                self.assertEqual(rawd[:4], b"DWAR")
                unk = struct.unpack_from("<I", rawd, 4)[0]
                self.assertIn(unk, (0, 1))
                length = struct.unpack_from("<I", rawd, 8)[0]
                self.assertGreater(length, 0)

    def test_icon_bundle_plist_generated(self):
        bundle = _make_icon_bundle(self.tmpdir)
        from actool.icon_bundle import compile_icon_bundle
        plist_path = os.path.join(self.outdir, "info.plist")
        compile_icon_bundle(
            bundle, self.outdir, "macosx", "26.0",
            app_icon="TestIcon", info_plist_path=plist_path)
        self.assertTrue(os.path.exists(plist_path))
        with open(plist_path) as f:
            content = f.read()
        self.assertIn("TestIcon", content)

    def test_icon_bundle_deduplicates_images(self):
        """Layers referencing the same filename are only stored once."""
        bundle = _make_icon_bundle(self.tmpdir, [SIMPLE_SVG])
        # Manually edit icon.json to reference same SVG twice
        icon_json_path = os.path.join(bundle, "icon.json")
        with open(icon_json_path) as f:
            icon_json = json.load(f)
        icon_json["groups"][0]["layers"].append(
            {"image-name": "1.svg", "name": "dup"})
        with open(icon_json_path, "w") as f:
            json.dump(icon_json, f)

        from actool.icon_bundle import compile_icon_bundle
        compile_icon_bundle(
            bundle, self.outdir, "macosx", "26.0", app_icon="TestIcon")
        car_path = os.path.join(self.outdir, "Assets.car")
        info = parse_car_info(car_path)
        self.assertEqual(info["rendition_count"], 1)


# ---------------------------------------------------------------------------
# CoreSVG rasterization tests (macOS only)
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_CORESVG, "CoreSVG not available (macOS only)")
class TestCoreSvgRasterization(unittest.TestCase):
    """Test SVG rasterization via CoreSVG framework."""

    def test_rasterize_produces_pixels(self):
        from actool.svg_raster import rasterize_svg
        data = rasterize_svg(SIMPLE_SVG, 64, 64)
        self.assertEqual(len(data), 64 * 64 * 4)
        self.assertTrue(any(b != 0 for b in data))

    def test_rasterize_2x_scale(self):
        from actool.svg_raster import rasterize_svg
        data = rasterize_svg(SIMPLE_SVG, 64, 64, scale=2)
        self.assertEqual(len(data), 128 * 128 * 4)

    def test_rasterize_bgra_byte_order(self):
        """Output is BGRA (little-endian premultiplied)."""
        from actool.svg_raster import rasterize_svg
        # Red circle SVG → center pixel should have B=0, R=255
        data = rasterize_svg(SIMPLE_SVG, 64, 64)
        center = 32 * 64 * 4 + 32 * 4
        b, g, r, a = data[center], data[center+1], data[center+2], data[center+3]
        self.assertGreater(a, 0, "Center pixel should be non-transparent")
        self.assertGreater(r, b, "Red channel should dominate for red circle")


# ---------------------------------------------------------------------------
# Host comparison tests (macOS only, requires system actool)
# ---------------------------------------------------------------------------

@unittest.skipUnless(
    has_system_actool() and has_assetutil(),
    "system actool and assetutil required")
class TestSvgHostComparison(unittest.TestCase):
    """Compare our SVG output against the system actool."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="actool_svg_host_test_")
        self.host_out = os.path.join(self.tmpdir, "host")
        self.our_out = os.path.join(self.tmpdir, "ours")
        os.makedirs(self.host_out)
        os.makedirs(self.our_out)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_svg_imageset_rendition_structure_matches_host(self):
        catalog = _make_svg_imageset_catalog(self.tmpdir)

        compile_with_system_actool(catalog, self.host_out)
        compile_catalog(catalog, self.our_out, "macosx", "11.0")

        host_car = os.path.join(self.host_out, "Assets.car")
        our_car = os.path.join(self.our_out, "Assets.car")
        if not os.path.exists(host_car):
            self.skipTest("host actool did not produce Assets.car")

        host_csis = parse_car_csi_by_name(host_car)
        our_csis = parse_car_csi_by_name(our_car)

        host_svg = host_csis.get("icon.svg", [])
        our_svg = our_csis.get("icon.svg", [])

        # Same number of renditions
        self.assertEqual(len(our_svg), len(host_svg),
                         f"Rendition count: ours={len(our_svg)} host={len(host_svg)}")

        # Same layouts
        host_layouts = sorted(e["layout"] for e in host_svg)
        our_layouts = sorted(e["layout"] for e in our_svg)
        self.assertEqual(our_layouts, host_layouts)

        # Vector rendition fields match
        host_vec = [e for e in host_svg if e["layout"] == car.LAYOUT_PDF]
        our_vec = [e for e in our_svg if e["layout"] == car.LAYOUT_PDF]
        if host_vec and our_vec:
            self.assertEqual(our_vec[0]["pixel_format"],
                             host_vec[0]["pixel_format"])
            self.assertEqual(our_vec[0]["flags"], host_vec[0]["flags"])

    def test_svg_compression_matches_host(self):
        # Use a large SVG so compression is exercised
        large_svg = (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128"'
            b' viewBox="0 0 128 128">'
            + b'<circle cx="32" cy="32" r="30" fill="#FF0000"/>' * 10
            + b'</svg>'
        )
        catalog = _make_svg_imageset_catalog(self.tmpdir, svg_data=large_svg)

        compile_with_system_actool(catalog, self.host_out)
        compile_catalog(catalog, self.our_out, "macosx", "11.0")

        host_car = os.path.join(self.host_out, "Assets.car")
        our_car = os.path.join(self.our_out, "Assets.car")
        if not os.path.exists(host_car):
            self.skipTest("host actool did not produce Assets.car")

        host_csis = parse_car_csi_by_name(host_car)
        our_csis = parse_car_csi_by_name(our_car)

        host_vec = [e for e in host_csis.get("icon.svg", [])
                    if e["layout"] == car.LAYOUT_PDF]
        our_vec = [e for e in our_csis.get("icon.svg", [])
                   if e["layout"] == car.LAYOUT_PDF]
        if not host_vec or not our_vec:
            self.skipTest("no vector rendition found")

        # RAWD header and payload should match
        host_rawd = host_vec[0]["rend"]
        our_rawd = our_vec[0]["rend"]
        self.assertEqual(host_rawd[:4], our_rawd[:4])  # DWAR magic
        host_unk = struct.unpack_from("<I", host_rawd, 4)[0]
        our_unk = struct.unpack_from("<I", our_rawd, 4)[0]
        self.assertEqual(our_unk, host_unk)
        host_payload = host_rawd[12:]
        our_payload = our_rawd[12:]
        self.assertEqual(our_payload, host_payload)


if __name__ == "__main__":
    unittest.main()
