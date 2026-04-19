"""Tests for symbol name generation helpers."""

import unittest

from actool.symbols import _objc_identifier, _swift_identifier


class TestObjCIdentifier(unittest.TestCase):

    def test_simple(self):
        self.assertEqual(_objc_identifier("Img001"), "Img001")
        self.assertEqual(_objc_identifier("TestAccent"), "TestAccent")

    def test_separator_split(self):
        self.assertEqual(_objc_identifier("my-image"), "MyImage")
        self.assertEqual(_objc_identifier("test_color"), "TestColor")
        self.assertEqual(_objc_identifier("foo.bar"), "FooBar")
        self.assertEqual(_objc_identifier("All Caps"), "AllCaps")

    def test_all_uppercase_word_preserved(self):
        self.assertEqual(_objc_identifier("IMAGE_test"), "IMAGETest")

    def test_digit_letter_boundary(self):
        self.assertEqual(_objc_identifier("123num"), "123Num")


class TestSwiftIdentifier(unittest.TestCase):

    def test_simple(self):
        self.assertEqual(_swift_identifier("Img001", "image"), "img001")
        self.assertEqual(_swift_identifier("TestAccent", "color"),
                         "testAccent")

    def test_strip_trailing_type_suffix(self):
        self.assertEqual(_swift_identifier("foo_image", "image"), "foo")
        self.assertEqual(_swift_identifier("bar_color", "color"), "bar")
        self.assertEqual(_swift_identifier("my-image", "image"), "my")
        self.assertEqual(_swift_identifier("myImage", "image"), "my")

    def test_do_not_strip_non_trailing(self):
        self.assertEqual(_swift_identifier("image_foo", "image"), "imageFoo")

    def test_leading_acronym_lowercased(self):
        self.assertEqual(_swift_identifier("IMAGE_test", "image"),
                         "imageTest")

    def test_digit_prefix_underscored(self):
        self.assertEqual(_swift_identifier("123num", "image"), "_123Num")


if __name__ == "__main__":
    unittest.main()
