"""Field-level comparisons of our Assets.car against /usr/bin/actool output.

These tests ensure specific CAR fields that we recently fixed (template
bitmapEncoding, color rendition shape, GA8 colorspace, APPEARANCEKEYS,
color-component parsing) match the host actool byte-for-byte where relevant.
"""

import json
import os
import shutil
import struct
import tempfile
import unittest

from PIL import Image

from actool.compiler import compile_catalog
from tests.helpers import (
    REF_XCASSETS,
    compile_with_system_actool,
    has_system_actool,
    parse_car_bom_tree,
    parse_car_csi_by_name,
    parse_colr_rendition,
)


@unittest.skipUnless(has_system_actool(), "system actool not available")
class TestHostFieldComparison(unittest.TestCase):
    """Compile ref samples with ours + system and compare individual fields."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="actool_hostfields_")
        our_dir = os.path.join(cls.tmpdir, "ours")
        sys_dir = os.path.join(cls.tmpdir, "system")
        compile_catalog(REF_XCASSETS, our_dir, "macosx", "11.0",
                        app_icon="AppIcon",
                        info_plist_path=os.path.join(our_dir, "Info.plist"))
        compile_with_system_actool(REF_XCASSETS, sys_dir, app_icon="AppIcon",
                                   min_deploy="11.0")
        cls.our_car = os.path.join(our_dir, "Assets.car")
        cls.sys_car = os.path.join(sys_dir, "Assets.car")
        cls.ours = parse_car_csi_by_name(cls.our_car)
        cls.sys = parse_car_csi_by_name(cls.sys_car)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    # --- Color renditions (TestAccent) -------------------------------------

    def test_testaccent_has_two_variants(self):
        self.assertEqual(len(self.ours.get("TestAccent", [])), 2)
        self.assertEqual(len(self.sys.get("TestAccent", [])), 2)

    def test_testaccent_csi_fields_match_system(self):
        """CSI header fields for colors: layout, cs, flags, bitmaplist_unknown."""
        ours = self.ours["TestAccent"]
        sys = self.sys["TestAccent"]
        # Sort both by first color component so we compare the same variants.
        ours_s = sorted(ours, key=lambda e: parse_colr_rendition(e["rend"])["components"][0])
        sys_s = sorted(sys, key=lambda e: parse_colr_rendition(e["rend"])["components"][0])
        for o, s in zip(ours_s, sys_s):
            self.assertEqual(o["layout"], s["layout"], "color layout mismatch")
            self.assertEqual(o["cs"], s["cs"],
                             "color CSI header colorspace mismatch")
            self.assertEqual(o["flags"], s["flags"], "color flags mismatch")
            self.assertEqual(o["bitmaplist_unknown"], s["bitmaplist_unknown"],
                             "color bitmaplist_unknown mismatch")

    def test_testaccent_colr_fields_match_system(self):
        """COLR rendition data: version, colorspace, component values."""
        ours = sorted(self.ours["TestAccent"],
                      key=lambda e: parse_colr_rendition(e["rend"])["components"][0])
        sys = sorted(self.sys["TestAccent"],
                     key=lambda e: parse_colr_rendition(e["rend"])["components"][0])
        for o, s in zip(ours, sys):
            oc = parse_colr_rendition(o["rend"])
            sc = parse_colr_rendition(s["rend"])
            self.assertEqual(oc["version"], sc["version"],
                             "COLR version mismatch")
            self.assertEqual(oc["colorspace"], sc["colorspace"],
                             "COLR colorspace byte mismatch")
            self.assertEqual(oc["components"], sc["components"],
                             "COLR component values differ")

    def test_testaccent_blend_opacity_matches_system(self):
        """Color renditions carry BlendModeAndOpacity (0x03EC) with opacity 0.0."""
        for e in self.ours["TestAccent"] + self.sys["TestAccent"]:
            blend = e["tlvs"].get(0x03EC)
            self.assertIsNotNone(blend, "missing blend TLV on color")
            mode, opacity = struct.unpack("<If", blend[:8])
            self.assertEqual(mode, 0)
            self.assertEqual(opacity, 0.0)

    # --- Template rendering intent (TemplateIcon) --------------------------

    def _template_entries(self, parsed):
        return [parsed[n][0] for n in ("icon.png", "icon@2x.png")
                if n in parsed]

    def test_template_icon_bitmap_encoding_matches_system(self):
        """TemplateIcon renditions must carry bitmapEncoding=template (flags 0x08)."""
        ours = self._template_entries(self.ours)
        sys = self._template_entries(self.sys)
        self.assertEqual(len(ours), 2)
        self.assertEqual(len(sys), 2)
        # bitmapEncoding lives in bits 2-5 of flags. Compare those bits only,
        # isolating from the isOpaque bit.
        for o, s in zip(ours, sys):
            self.assertEqual((o["flags"] >> 2) & 0xF, (s["flags"] >> 2) & 0xF,
                             f"template bitmapEncoding mismatch "
                             f"(ours={o['flags']:#x} sys={s['flags']:#x})")
            # Should specifically be 2 (=template).
            self.assertEqual((o["flags"] >> 2) & 0xF, 2)

    # --- GA8 colorspace ----------------------------------------------------

    def test_ga8_csi_colorspace_matches_system(self):
        """Every GA8 rendition in our CAR has the same CSI cs byte as system's."""
        def ga8_entries(parsed):
            out = {}
            for name, entries in parsed.items():
                for e in entries:
                    if e["pixel_format"] == b" 8AG":
                        out.setdefault(name, []).append(e["cs"])
            return out

        ours = ga8_entries(self.ours)
        sys = ga8_entries(self.sys)
        # Only compare names present in both (atlas names may differ).
        common = set(ours) & set(sys)
        self.assertGreater(len(common), 0, "no overlapping GA8 entries")
        for name in sorted(common):
            self.assertEqual(sorted(ours[name]), sorted(sys[name]),
                             f"GA8 cs mismatch for {name}")
        # And all entries should use cs=2 (gray gamma 2.2).
        for name, values in ours.items():
            for v in values:
                self.assertEqual(v, 2, f"ours {name} has cs={v}, expected 2")
        for name, values in sys.items():
            for v in values:
                self.assertEqual(v, 2, f"sys {name} has cs={v}, expected 2")

    # --- APPEARANCEKEYS tree -----------------------------------------------

    def test_appearancekeys_tree_matches_system(self):
        """APPEARANCEKEYS BOM tree must exist and contain the same keys."""
        ours = parse_car_bom_tree(self.our_car, "APPEARANCEKEYS")
        sys = parse_car_bom_tree(self.sys_car, "APPEARANCEKEYS")
        self.assertIsNotNone(sys, "system actool did not emit APPEARANCEKEYS")
        self.assertIsNotNone(ours, "our actool did not emit APPEARANCEKEYS")
        our_keys = {k: v for k, v in ours}
        sys_keys = {k: v for k, v in sys}
        self.assertEqual(set(our_keys), set(sys_keys),
                         "APPEARANCEKEYS name set differs")
        for k in sys_keys:
            self.assertEqual(our_keys[k], sys_keys[k],
                             f"APPEARANCEKEYS value for {k!r} differs")


@unittest.skipUnless(has_system_actool(), "system actool not available")
class TestColorComponentFormats(unittest.TestCase):
    """Colors with integer/hex component formats must match system output."""

    FORMATS = {
        # name -> (components dict, expected rgba floats)
        "IntColor": (
            {"red": "128", "green": "64", "blue": "255", "alpha": "255"},
            (128 / 255.0, 64 / 255.0, 1.0, 1.0),
        ),
        "HexColor": (
            {"red": "0x80", "green": "0x40", "blue": "0xFF", "alpha": "0xFF"},
            (0x80 / 255.0, 0x40 / 255.0, 1.0, 1.0),
        ),
        "FloatColor": (
            {"red": "0.500", "green": "0.250", "blue": "1.000", "alpha": "1.000"},
            (0.5, 0.25, 1.0, 1.0),
        ),
    }

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="actool_colorfmt_")
        catalog = os.path.join(cls.tmpdir, "Colors.xcassets")
        os.makedirs(catalog, exist_ok=True)
        with open(os.path.join(catalog, "Contents.json"), "w") as f:
            json.dump({"info": {"author": "xcode", "version": 1}}, f)
        for name, (components, _) in cls.FORMATS.items():
            cset = os.path.join(catalog, f"{name}.colorset")
            os.makedirs(cset, exist_ok=True)
            with open(os.path.join(cset, "Contents.json"), "w") as f:
                json.dump({
                    "info": {"author": "xcode", "version": 1},
                    "colors": [{
                        "idiom": "universal",
                        "color": {
                            "color-space": "srgb",
                            "components": components,
                        },
                    }],
                }, f)
        cls.catalog = catalog
        our_dir = os.path.join(cls.tmpdir, "ours")
        sys_dir = os.path.join(cls.tmpdir, "sys")
        compile_catalog(catalog, our_dir, "macosx", "11.0")
        compile_with_system_actool(catalog, sys_dir, min_deploy="11.0")
        cls.ours = parse_car_csi_by_name(os.path.join(our_dir, "Assets.car"))
        cls.sys = parse_car_csi_by_name(os.path.join(sys_dir, "Assets.car"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _components(self, parsed, name):
        entries = parsed.get(name, [])
        self.assertEqual(len(entries), 1, f"expected one rendition for {name}")
        colr = parse_colr_rendition(entries[0]["rend"])
        self.assertIsNotNone(colr, f"no COLR for {name}")
        return colr["components"]

    def test_components_match_system_for_each_format(self):
        for name in self.FORMATS:
            with self.subTest(name=name):
                our_c = self._components(self.ours, name)
                sys_c = self._components(self.sys, name)
                self.assertEqual(our_c, sys_c,
                                 f"{name} components differ "
                                 f"(ours={our_c} sys={sys_c})")
