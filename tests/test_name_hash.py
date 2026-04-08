"""Tests for _hash_name, which must match /usr/bin/actool byte-for-byte.

The hash is used to assign 16-bit identifiers in FACETKEYS / rendition keys.
CoreUI doesn't require matching Apple's exact values, but matching lets our
output diff cleanly against system actool's and catches accidental
regressions in the hash implementation.
"""

import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest

from PIL import Image

from actool.name_hash import hash_name as _hash_name
from tests.helpers import (
    has_system_actool,
    parse_car_bom_tree,
)


# Golden values captured from /usr/bin/actool for representative names.
# If these change, either Apple changed their algorithm or we regressed.
GOLDEN = {
    # Single-char
    "a": 0xa2ca,
    "z": 0x5843,
    # Short names
    "pp": 0x4062,
    "qqq": 0xbbe2,
    # Reference-catalog names
    "Img001": 0x27d5,
    "Img002": 0xb436,
    "Img009": 0x8add,
    "AppIcon": 0x1ac1,
    # Longer novel names
    "HelloWorld": 0x07ca,
    "button_primary": 0xdf14,
    "really_long_name_goes_here_abc_xyz_123": 0x3446,
    "foo.bar.baz": 0xee88,
    "profile-avatar@2x-like": 0x4206,
    # >= 10 chars (crosses the 4th 16-bit chunk boundary of the accumulator)
    "aaaaaaaaaa": 0xb07b,
    "aaaaaaaaaaaaaaa": 0x5275,
}


class TestHashNameGolden(unittest.TestCase):
    """Fixed vectors captured from /usr/bin/actool."""

    def test_golden_vectors(self):
        for name, expected in GOLDEN.items():
            with self.subTest(name=name):
                self.assertEqual(_hash_name(name), expected,
                                 f"hash({name!r}) mismatch")

    def test_hash_is_nonzero(self):
        # The function returns 1 instead of 0 to avoid zero identifiers.
        # Empty string happens to hash to nonzero anyway, but ensure the
        # contract holds.
        for name in ("a", "b", "Img001", "HelloWorld"):
            self.assertNotEqual(_hash_name(name), 0)


@unittest.skipUnless(has_system_actool(), "system actool not available")
class TestHashNameMatchesSystemActool(unittest.TestCase):
    """Compile a catalog with the system actool and compare every FACETKEYS
    identifier against our hash function."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="actool_hash_")
        catalog = os.path.join(cls.tmpdir, "HashProbe.xcassets")
        os.makedirs(catalog)
        with open(os.path.join(catalog, "Contents.json"), "w") as f:
            json.dump({"info": {"author": "xcode", "version": 1}}, f)

        # Diverse mix: short, medium, long, punctuation, digits.
        names = [
            "a", "zz", "abc",
            "icon", "button", "badge",
            "NavBack", "tab_home", "menu.open",
            "Img001", "Img999",
            "very_long_asset_name_that_overflows_the_accumulator_1234",
            "x" * 32,
            "mix3d.With-Various_Chars@2x",
        ]
        for n in names:
            d = os.path.join(catalog, f"{n}.imageset")
            os.makedirs(d)
            Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(
                os.path.join(d, "img.png"))
            with open(os.path.join(d, "Contents.json"), "w") as f:
                json.dump({
                    "images": [{"filename": "img.png", "idiom": "mac",
                                "scale": "1x"}],
                    "info": {"author": "xcode", "version": 1},
                }, f)
        cls.names = names

        sys_out = os.path.join(cls.tmpdir, "sys")
        os.makedirs(sys_out)
        subprocess.run([
            "/usr/bin/actool", "--compile", sys_out,
            "--platform", "macosx",
            "--minimum-deployment-target", "11.0",
            catalog,
        ], capture_output=True, check=True)
        cls.sys_car = os.path.join(sys_out, "Assets.car")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_every_facetkey_identifier_matches(self):
        fk = parse_car_bom_tree(self.sys_car, "FACETKEYS")
        self.assertIsNotNone(fk)
        sys_ids = {}
        for key, val in fk:
            name = key.decode("utf-8", "replace")
            num = struct.unpack("<H", val[4:6])[0]
            attrs = dict(struct.unpack("<HH", val[6 + i * 4:10 + i * 4])
                         for i in range(num))
            if 17 in attrs:
                sys_ids[name] = attrs[17]
        self.assertGreater(len(sys_ids), 0, "no identifiers extracted")
        for name in self.names:
            with self.subTest(name=name):
                self.assertIn(name, sys_ids, f"{name} missing from sys car")
                self.assertEqual(_hash_name(name), sys_ids[name],
                                 f"hash({name!r}) != system id")
