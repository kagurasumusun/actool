"""Tests for CLI output formats and options."""

import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.helpers import REF_XCASSETS


def run_actool(*args):
    """Run our actool and return (stdout, stderr, returncode)."""
    cmd = [sys.executable, "-m", "actool"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return result.stdout, result.stderr, result.returncode


class TestVersion(unittest.TestCase):

    def test_version_xml(self):
        stdout, _, rc = run_actool("--version")
        self.assertEqual(rc, 0)
        data = plistlib.loads(stdout.encode())
        ver = data["com.apple.actool.version"]
        self.assertIn("bundle-version", ver)
        self.assertIn("short-bundle-version", ver)

    def test_version_human_readable(self):
        stdout, _, rc = run_actool("--version", "--output-format",
                                   "human-readable-text")
        self.assertEqual(rc, 0)
        self.assertIn("/* com.apple.actool.version */", stdout)
        self.assertIn("bundle-version:", stdout)

    def test_version_no_document_required(self):
        stdout, _, rc = run_actool("--version")
        self.assertEqual(rc, 0)


class TestPrintContents(unittest.TestCase):

    def test_print_contents_xml(self):
        stdout, _, rc = run_actool("--print-contents", REF_XCASSETS)
        self.assertEqual(rc, 0)
        data = plistlib.loads(stdout.encode())
        contents = data["com.apple.actool.catalog-contents"]
        self.assertIsInstance(contents, list)
        self.assertGreater(len(contents), 0)
        self.assertEqual(contents[0]["filename"], "Catalog.xcassets")
        self.assertIn("children", contents[0])

    def test_print_contents_human_readable(self):
        stdout, _, rc = run_actool("--print-contents", "--output-format",
                                   "human-readable-text", REF_XCASSETS)
        self.assertEqual(rc, 0)
        self.assertIn("/* com.apple.actool.catalog-contents */", stdout)
        self.assertIn("filename: Catalog.xcassets", stdout)


class TestCompile(unittest.TestCase):

    def test_compile_xml_output(self):
        tmpdir = tempfile.mkdtemp()
        try:
            outdir = os.path.join(tmpdir, "out")
            stdout, _, rc = run_actool(
                "--compile", outdir, "--platform", "macosx",
                "--minimum-deployment-target", "11.0",
                "--app-icon", "AppIcon",
                "--output-partial-info-plist",
                os.path.join(outdir, "Info.plist"),
                REF_XCASSETS)
            self.assertEqual(rc, 0)
            data = plistlib.loads(stdout.encode())
            files = data["com.apple.actool.compilation-results"]["output-files"]
            self.assertGreater(len(files), 0)
            # Check output files exist
            self.assertTrue(os.path.exists(os.path.join(outdir, "Assets.car")))
            self.assertTrue(os.path.exists(os.path.join(outdir, "Info.plist")))
        finally:
            shutil.rmtree(tmpdir)

    def test_compile_human_readable(self):
        tmpdir = tempfile.mkdtemp()
        try:
            outdir = os.path.join(tmpdir, "out")
            stdout, _, rc = run_actool(
                "--compile", outdir, "--output-format", "human-readable-text",
                "--platform", "macosx", "--minimum-deployment-target", "11.0",
                REF_XCASSETS)
            self.assertEqual(rc, 0)
            self.assertIn("/* com.apple.actool.compilation-results */", stdout)
            self.assertIn("Assets.car", stdout)
        finally:
            shutil.rmtree(tmpdir)

    def test_standalone_icon_none(self):
        """--standalone-icon-behavior none suppresses ICNS."""
        tmpdir = tempfile.mkdtemp()
        try:
            outdir = os.path.join(tmpdir, "out")
            run_actool("--compile", outdir, "--platform", "macosx",
                       "--minimum-deployment-target", "11.0",
                       "--app-icon", "AppIcon",
                       "--standalone-icon-behavior", "none",
                       REF_XCASSETS)
            self.assertFalse(os.path.exists(
                os.path.join(outdir, "AppIcon.icns")))
        finally:
            shutil.rmtree(tmpdir)


class TestExportDependencyInfo(unittest.TestCase):

    def test_dependency_info_format(self):
        """--export-dependency-info writes binary dep info."""
        tmpdir = tempfile.mkdtemp()
        try:
            outdir = os.path.join(tmpdir, "out")
            depfile = os.path.join(tmpdir, "deps.d")
            plist_path = os.path.join(tmpdir, "Info.plist")
            run_actool(
                "--compile", outdir, "--platform", "macosx",
                "--minimum-deployment-target", "11.0",
                "--app-icon", "AppIcon",
                "--output-partial-info-plist", plist_path,
                "--export-dependency-info", depfile,
                REF_XCASSETS)
            self.assertTrue(os.path.exists(depfile))
            with open(depfile, "rb") as f:
                data = f.read()
            # Version record: \x00 + "actool-..." + \x00
            self.assertEqual(data[0:1], b"\x00")
            self.assertIn(b"actool-", data)
            # Input record: \x10 + path
            self.assertIn(b"\x10", data)
            abs_input = os.path.abspath(REF_XCASSETS).encode()
            self.assertIn(abs_input, data)
            # Output records: \x40 + path
            self.assertIn(b"\x40", data)
            self.assertIn(b"Assets.car", data)
        finally:
            shutil.rmtree(tmpdir)

    def test_no_dependency_info_by_default(self):
        """Without --export-dependency-info, no dep file is written."""
        tmpdir = tempfile.mkdtemp()
        try:
            outdir = os.path.join(tmpdir, "out")
            depfile = os.path.join(tmpdir, "deps.d")
            run_actool(
                "--compile", outdir, "--platform", "macosx",
                "--minimum-deployment-target", "11.0",
                REF_XCASSETS)
            self.assertFalse(os.path.exists(depfile))
        finally:
            shutil.rmtree(tmpdir)


if __name__ == "__main__":
    unittest.main()
