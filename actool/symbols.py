"""Objective-C/Swift asset symbol generation.

Produces two artifacts used by Xcode's generated-symbols feature:
- An Objective-C header declaring ACImageName/ACColorName constants.
- A plist-XML symbol index mapping assets to objc/swift symbol names.

Matches Apple's actool --generate-objc-asset-symbols and
--generate-asset-symbol-index output closely for common naming patterns.
"""

import json
import os
import plistlib
from pathlib import Path


PLATFORM_IDIOMS = {
    "macosx": {"mac", "universal"},
    "iphoneos": {"iphone", "ipad", "ios-marketing", "car", "universal"},
    "iphonesimulator": {"iphone", "ipad", "ios-marketing", "car", "universal"},
    "watchos": {"watch", "universal"},
    "watchsimulator": {"watch", "universal"},
    "appletvos": {"tv", "universal"},
    "appletvsimulator": {"tv", "universal"},
}

# Type-name suffixes that Apple strips from swift symbols when they appear as
# the last word of the asset name.
_SWIFT_STRIP_SUFFIX = {
    "image": "image",
    "color": "color",
    "symbol": "symbol",
}


def _entry_applies(contents_path: Path, platform: str,
                   keys: tuple[str, ...]) -> bool:
    """Return True if any entry in Contents.json matches the platform idiom."""
    try:
        with open(contents_path) as f:
            contents = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False

    allowed = PLATFORM_IDIOMS.get(platform, {"universal"})
    for key in keys:
        for entry in contents.get(key, []):
            idiom = entry.get("idiom", "universal")
            if idiom in allowed:
                return True
    return False


def _walk_assets(xcassets_path: str, platform: str,
                 rel_prefix: str = "",
                 namespace: str = "") -> list[tuple[str, str, str, str]]:
    """Yield (kind, leaf_name, namespaced_name, relative_path) for each asset.

    kind is "image" or "color". relative_path is POSIX-style without "./"
    prefix — callers add it.
    """
    results: list[tuple[str, str, str, str]] = []
    root = Path(xcassets_path)
    if not root.is_dir():
        return results

    for item in sorted(root.iterdir()):
        if not item.is_dir():
            continue
        contents = item / "Contents.json"
        name = item.stem
        namespaced = f"{namespace}{name}"
        rel = f"{rel_prefix}{item.name}" if rel_prefix else item.name
        if item.suffix == ".imageset":
            if _entry_applies(contents, platform, ("images",)):
                results.append(("image", name, namespaced, rel))
        elif item.suffix == ".colorset":
            if _entry_applies(contents, platform, ("colors",)):
                results.append(("color", name, namespaced, rel))
        elif not item.suffix:
            child_ns = namespace
            if contents.exists():
                try:
                    with open(contents) as f:
                        meta = json.load(f)
                    if meta.get("properties", {}).get("provides-namespace"):
                        child_ns = f"{namespace}{name}/"
                except (OSError, json.JSONDecodeError):
                    pass
            child_rel = f"{rel_prefix}{item.name}/"
            results.extend(_walk_assets(
                str(item), platform, child_rel, child_ns))

    return results


def _split_words(name: str) -> list[str]:
    """Split an identifier-like name into words.

    Splits on non-alphanumeric separators, digit/letter boundaries, and
    camelCase transitions (lower→upper, UPPER→UpperLower).
    """
    words: list[str] = []
    current = ""
    prev_kind: str | None = None

    def kind_of(ch: str) -> str:
        if ch.isalpha():
            return "upper" if ch.isupper() else "lower"
        if ch.isdigit():
            return "digit"
        return "sep"

    for ch in name:
        k = kind_of(ch)
        if k == "sep":
            if current:
                words.append(current)
                current = ""
            prev_kind = "sep"
            continue
        if prev_kind is None or prev_kind == "sep":
            current = ch
        elif k == prev_kind:
            current += ch
        elif prev_kind == "lower" and k == "upper":
            words.append(current)
            current = ch
        elif prev_kind == "upper" and k == "lower":
            # UPPERLower: last upper belongs with the lower run
            if len(current) > 1:
                words.append(current[:-1])
                current = current[-1] + ch
            else:
                current += ch
        else:
            # digit/letter transition
            words.append(current)
            current = ch
        prev_kind = k

    if current:
        words.append(current)
    return words


def _objc_identifier(name: str) -> str:
    """Convert an asset name to the identifier suffix used in ObjC symbols.

    Each word's first character is uppercased; the rest of each word is
    preserved so all-caps words keep their case (e.g. IMAGE_test → IMAGETest).
    """
    words = _split_words(name)
    parts = []
    for w in words:
        if not w:
            continue
        if w[0].isalpha():
            parts.append(w[0].upper() + w[1:])
        else:
            parts.append(w)
    return "".join(parts)


def _swift_identifier(name: str, kind: str) -> str:
    """Convert an asset name to the swift symbol (camelCase).

    Strips the trailing word if it matches the asset-type suffix
    (image/color/symbol). Prepends '_' if the result starts with a digit.
    """
    words = _split_words(name)
    strip = _SWIFT_STRIP_SUFFIX.get(kind)
    if strip and len(words) > 1 and words[-1].lower() == strip:
        words = words[:-1]

    parts = []
    for i, w in enumerate(words):
        if not w:
            continue
        if i == 0:
            if w.isalpha() and w.isupper():
                # Leading acronym (URL, IMAGE) becomes fully lowercase
                parts.append(w.lower())
            elif w[0].isalpha():
                parts.append(w[0].lower() + w[1:])
            else:
                parts.append(w)
        else:
            if w[0].isalpha():
                parts.append(w[0].upper() + w[1:])
            else:
                parts.append(w)

    result = "".join(parts)
    if result and result[0].isdigit():
        result = "_" + result
    return result


def _objc_symbol_name(kind: str, leaf_name: str) -> str:
    return f"AC{'Color' if kind == 'color' else 'Image'}Name" \
           f"{_objc_identifier(leaf_name)}"


def generate_symbols_header(xcassets_path: str, output_path: str,
                            bundle_identifier: str, platform: str) -> None:
    """Write an Objective-C header with ACImageName/ACColorName constants.

    Uses the full namespaced name as both the identifier suffix and the
    string literal.
    """
    assets = _walk_assets(xcassets_path, platform)
    images = sorted([a for a in assets if a[0] == "image"], key=lambda a: a[2])
    colors = sorted([a for a in assets if a[0] == "color"], key=lambda a: a[2])

    lines = [
        "#import <Foundation/Foundation.h>\n",
        "\n",
        "#if __has_attribute(swift_private)\n",
        "#define AC_SWIFT_PRIVATE __attribute__((swift_private))\n",
        "#else\n",
        "#define AC_SWIFT_PRIVATE\n",
        "#endif\n",
        "\n",
    ]

    if colors:
        lines.append("/// The resource bundle ID.\n")
        lines.append(
            f"static NSString * const ACBundleID AC_SWIFT_PRIVATE = "
            f"@\"{bundle_identifier}\";\n")
        lines.append("\n")

    for _, _, namespaced, _ in colors:
        ident = _objc_identifier(namespaced)
        lines.append(
            f"/// The \"{namespaced}\" asset catalog color resource.\n")
        lines.append(
            f"static NSString * const ACColorName{ident} AC_SWIFT_PRIVATE = "
            f"@\"{namespaced}\";\n")
        lines.append("\n")

    for _, _, namespaced, _ in images:
        ident = _objc_identifier(namespaced)
        lines.append(
            f"/// The \"{namespaced}\" asset catalog image resource.\n")
        lines.append(
            f"static NSString * const ACImageName{ident} AC_SWIFT_PRIVATE = "
            f"@\"{namespaced}\";\n")
        lines.append("\n")

    lines.append("#undef AC_SWIFT_PRIVATE\n")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as f:
        f.write("".join(lines))


def generate_symbol_index(xcassets_path: str, output_path: str,
                          platform: str) -> None:
    """Write the plist-XML symbol index file.

    Contains colors/images/symbols arrays. Each entry describes an asset's
    catalog path, relative path, and its objc/swift symbol identifiers.
    """
    assets = _walk_assets(xcassets_path, platform)
    catalog_abs = os.path.abspath(xcassets_path)

    def entry(kind: str, leaf: str, rel: str) -> dict:
        return {
            "catalogPath": catalog_abs,
            "objcSymbol": _objc_symbol_name(kind, leaf),
            "relativePath": f"./{rel}",
            "swiftSymbol": _swift_identifier(leaf, kind),
        }

    colors = sorted([a for a in assets if a[0] == "color"], key=lambda a: a[3])
    images = sorted([a for a in assets if a[0] == "image"], key=lambda a: a[3])

    data = {
        "colors": [entry("color", leaf, rel) for _, leaf, _, rel in colors],
        "images": [entry("image", leaf, rel) for _, leaf, _, rel in images],
        "symbols": [],
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f:
        plistlib.dump(data, f, fmt=plistlib.FMT_XML)
