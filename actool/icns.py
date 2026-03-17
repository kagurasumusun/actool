"""
ICNS (macOS icon) file writer.

Creates .icns files from PNG images at various sizes.
Apple's actool generates ICNS with specific type codes:
- ic04: 16x16 ARGB with PackBits compression per channel
- ic11: 16@2x = 32x32 PNG
- ic07: 128x128 PNG
- ic13: 128@2x = 256x256 PNG
"""

import struct
from PIL import Image, PngImagePlugin
import io


# ICNS entries that Apple's actool generates
# (point_size, scale, type_code, format)
ICNS_ENTRIES = [
    (128, 2, b"ic13", "png"),   # 256x256 (128@2x)
    (16, 2, b"ic11", "png"),    # 32x32 (16@2x)
    (16, 1, b"ic04", "argb"),   # 16x16 ARGB PackBits
    (128, 1, b"ic07", "png"),   # 128x128
]


def _packbits_compress(data: bytes) -> bytes:
    """PackBits compression (ICNS variant)."""
    result = bytearray()
    i = 0
    n = len(data)

    while i < n:
        # Look for a run of identical bytes
        run_start = i
        if i + 1 < n and data[i] == data[i + 1]:
            # Count run length (max 130)
            run_val = data[i]
            run_len = 1
            while i + run_len < n and data[i + run_len] == run_val and run_len < 130:
                run_len += 1
            if run_len >= 3:
                result.append(run_len + 125)  # 128 + run_len - 3
                result.append(run_val)
                i += run_len
                continue

        # Literal run (non-repeating bytes, max 128)
        lit_start = i
        lit_len = 0
        while i + lit_len < n and lit_len < 128:
            if (i + lit_len + 2 < n and
                    data[i + lit_len] == data[i + lit_len + 1] == data[i + lit_len + 2]):
                break
            lit_len += 1
        if lit_len > 0:
            result.append(lit_len - 1)
            result.extend(data[i:i + lit_len])
            i += lit_len
        else:
            # Shouldn't happen, but handle edge case
            result.append(0)
            result.append(data[i])
            i += 1

    return bytes(result)


def _make_argb(img_path: str, pixel_size: int) -> bytes:
    """Create ARGB data with PackBits compression for an icon."""
    img = Image.open(img_path).convert("RGBA")
    if img.width != pixel_size or img.height != pixel_size:
        img = img.resize((pixel_size, pixel_size), Image.LANCZOS)

    pixels = img.tobytes()  # RGBA interleaved
    n_pixels = pixel_size * pixel_size

    # Split into separate channels
    a_channel = bytes(pixels[i + 3] for i in range(0, len(pixels), 4))
    r_channel = bytes(pixels[i] for i in range(0, len(pixels), 4))
    g_channel = bytes(pixels[i + 1] for i in range(0, len(pixels), 4))
    b_channel = bytes(pixels[i + 2] for i in range(0, len(pixels), 4))

    # PackBits compress each channel
    result = b"ARGB"
    result += _packbits_compress(a_channel)
    result += _packbits_compress(r_channel)
    result += _packbits_compress(g_channel)
    result += _packbits_compress(b_channel)

    return result


def _make_exif(width: int, height: int) -> bytes:
    """Generate EXIF data with PixelXDimension and PixelYDimension."""
    # Exif header
    buf = bytearray(b"Exif\x00\x00")
    # TIFF header (big-endian)
    buf += b"MM"  # big-endian
    buf += struct.pack(">H", 42)  # TIFF magic
    buf += struct.pack(">I", 8)  # offset to IFD0

    # IFD0: 1 entry (ExifIFD pointer)
    buf += struct.pack(">H", 1)  # count
    # Tag 0x8769 (ExifIFD), type LONG(4), count 1, value = offset to ExifIFD
    exif_ifd_offset = 8 + 2 + 12 + 4  # IFD0 header + 1 entry + next IFD ptr = 26
    buf += struct.pack(">HHII", 0x8769, 4, 1, exif_ifd_offset)
    buf += struct.pack(">I", 0)  # next IFD = 0

    # ExifIFD: 2 entries
    buf += struct.pack(">H", 2)
    buf += struct.pack(">HHII", 0xA002, 4, 1, width)   # PixelXDimension
    buf += struct.pack(">HHII", 0xA003, 4, 1, height)  # PixelYDimension
    buf += struct.pack(">I", 0)  # next IFD = 0

    return bytes(buf)


def _reencode_png(img_path: str) -> bytes:
    """Re-encode a PNG with sRGB and EXIF metadata (matching Apple's actool)."""
    img = Image.open(img_path)
    exif_data = _make_exif(img.width, img.height)

    buf = io.BytesIO()
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add(b"sRGB", bytes([0]))  # Perceptual rendering intent
    img.save(buf, format="PNG", exif=exif_data, pnginfo=pnginfo,
             compress_level=1)
    return buf.getvalue()


def create_icns(icon_images: list[tuple[str, int, int]], output_path: str):
    """Create an ICNS file from a list of (image_path, pixel_size, scale) tuples."""
    # Build a lookup: (point_size, scale) -> image_path
    lookup = {}
    for img_path, pixel_size, scale in icon_images:
        point_size = pixel_size // scale
        lookup[(point_size, scale)] = img_path

    entries = []
    for point_size, scale, type_code, fmt in ICNS_ENTRIES:
        key = (point_size, scale)
        if key not in lookup:
            continue

        img_path = lookup[key]

        if fmt == "argb":
            data = _make_argb(img_path, point_size * scale)
        else:
            # Re-encode PNG with sRGB + EXIF metadata
            data = _reencode_png(img_path)

        entries.append((type_code, data))

    if not entries:
        return

    # Build ICNS file
    total_size = 8
    for type_code, data in entries:
        total_size += 8 + len(data)

    with open(output_path, "wb") as f:
        f.write(b"icns")
        f.write(struct.pack(">I", total_size))
        for type_code, data in entries:
            f.write(type_code)
            f.write(struct.pack(">I", 8 + len(data)))
            f.write(data)
