"""Objective-C asset symbol header generation.

Produces a header file that declares string constants for asset catalog
resource names, so Swift/ObjC code can reference them in a type-safe way.
Matches the output of Apple's actool --generate-objc-asset-symbols.
"""

import json
import os
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


def _collect_assets(xcassets_path: str, platform: str,
                    namespace: str = "") -> tuple[list[str], list[str]]:
    """Walk the xcassets dir, return (image_names, color_names).

    Names include namespace prefixes for groups with provides-namespace.
    """
    images: list[str] = []
    colors: list[str] = []
    root = Path(xcassets_path)
    if not root.is_dir():
        return images, colors

    for item in sorted(root.iterdir()):
        if not item.is_dir():
            continue
        contents = item / "Contents.json"
        name = item.stem
        facet = f"{namespace}{name}"
        if item.suffix == ".imageset":
            if _entry_applies(contents, platform, ("images",)):
                images.append(facet)
        elif item.suffix == ".colorset":
            if _entry_applies(contents, platform, ("colors",)):
                colors.append(facet)
        elif not item.suffix:
            # Plain group directory, may provide namespace
            child_ns = namespace
            if contents.exists():
                try:
                    with open(contents) as f:
                        meta = json.load(f)
                    if meta.get("properties", {}).get("provides-namespace"):
                        child_ns = f"{namespace}{name}/"
                except (OSError, json.JSONDecodeError):
                    pass
            sub_images, sub_colors = _collect_assets(
                str(item), platform, child_ns)
            images.extend(sub_images)
            colors.extend(sub_colors)

    return images, colors


def _sanitize_identifier(name: str) -> str:
    """Convert asset name to a valid C identifier suffix.

    Replaces namespace separators and non-identifier characters.
    """
    out = []
    for ch in name:
        if ch.isalnum() or ch == "_":
            out.append(ch)
        # Drop slashes, dashes, etc. - Apple concatenates namespace parts
    return "".join(out)


def generate_symbols_header(xcassets_path: str, output_path: str,
                            bundle_identifier: str, platform: str) -> None:
    """Write an Objective-C header with ACImageName/ACColorName constants."""
    images, colors = _collect_assets(xcassets_path, platform)
    images.sort()
    colors.sort()

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

    # ACBundleID is only emitted when at least one color is present.
    if colors:
        lines.append("/// The resource bundle ID.\n")
        lines.append(
            f"static NSString * const ACBundleID AC_SWIFT_PRIVATE = "
            f"@\"{bundle_identifier}\";\n")
        lines.append("\n")

    for name in colors:
        ident = _sanitize_identifier(name)
        lines.append(f"/// The \"{name}\" asset catalog color resource.\n")
        lines.append(
            f"static NSString * const ACColorName{ident} AC_SWIFT_PRIVATE = "
            f"@\"{name}\";\n")
        lines.append("\n")

    for name in images:
        ident = _sanitize_identifier(name)
        lines.append(f"/// The \"{name}\" asset catalog image resource.\n")
        lines.append(
            f"static NSString * const ACImageName{ident} AC_SWIFT_PRIVATE = "
            f"@\"{name}\";\n")
        lines.append("\n")

    lines.append("#undef AC_SWIFT_PRIVATE\n")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as f:
        f.write("".join(lines))
