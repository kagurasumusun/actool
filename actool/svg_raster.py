"""
SVG rasterization via macOS CoreSVG private framework.
"""

import ctypes
import ctypes.util
from ctypes import c_void_p, c_size_t, c_double
import re
import pathlib


def _find_private_framework(name):
    """Locate a private framework relative to a known public framework."""
    anchor = ctypes.util.find_library("CoreGraphics")
    if not anchor:
        raise OSError("cannot locate CoreGraphics to derive SDK path")
    # anchor is e.g. .../Frameworks/CoreGraphics.framework/CoreGraphics
    # Walk up to the Frameworks dir, then derive PrivateFrameworks sibling
    frameworks_dir = pathlib.Path(anchor).parent.parent
    private_path = frameworks_dir.parent / "PrivateFrameworks" / f"{name}.framework" / name
    return str(private_path)


try:
    _CG = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreGraphics"))
    _CF = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
    _CoreSVG = ctypes.cdll.LoadLibrary(_find_private_framework("CoreSVG"))

    _CF.CFDataCreate.restype = c_void_p
    _CF.CFDataCreate.argtypes = [c_void_p, ctypes.c_char_p, c_size_t]
    _CF.CFRelease.argtypes = [c_void_p]

    _CoreSVG.CGSVGDocumentCreateFromData.restype = c_void_p
    _CoreSVG.CGSVGDocumentCreateFromData.argtypes = [c_void_p, c_void_p]

    _CoreSVG.CGContextDrawSVGDocument.restype = None
    _CoreSVG.CGContextDrawSVGDocument.argtypes = [c_void_p, c_void_p]

    _CG.CGBitmapContextCreate.restype = c_void_p
    _CG.CGBitmapContextCreate.argtypes = [
        c_void_p, c_size_t, c_size_t, c_size_t, c_size_t, c_void_p,
        ctypes.c_uint32]
    _CG.CGColorSpaceCreateWithName.restype = c_void_p
    _CG.CGColorSpaceCreateWithName.argtypes = [c_void_p]
    _CG.CGContextScaleCTM.argtypes = [c_void_p, c_double, c_double]
    _CG.CGBitmapContextGetData.restype = ctypes.POINTER(ctypes.c_ubyte)
    _CG.CGBitmapContextGetData.argtypes = [c_void_p]
    _CG.CGContextRelease.argtypes = [c_void_p]
    _CG.CGColorSpaceRelease.argtypes = [c_void_p]

    HAS_CORESVG = True
except (OSError, AttributeError):
    HAS_CORESVG = False


def _parse_svg_dimensions(svg_data: bytes) -> tuple[int, int]:
    """Extract width/height from SVG root element attributes."""
    text = svg_data[:2048].decode("utf-8", errors="replace")
    w_m = re.search(r'width="(\d+(?:\.\d+)?)"', text)
    h_m = re.search(r'height="(\d+(?:\.\d+)?)"', text)
    if w_m and h_m:
        return int(float(w_m.group(1))), int(float(h_m.group(1)))
    vb_m = re.search(r'viewBox="[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)"', text)
    if vb_m:
        return int(float(vb_m.group(1))), int(float(vb_m.group(2)))
    return 0, 0


def rasterize_svg(svg_data: bytes, width: int, height: int,
                  scale: int = 1) -> bytes:
    """Rasterize SVG data into BGRA premultiplied-alpha pixel data.

    Returns raw pixel bytes in BGRA byte order (little-endian ARGB),
    sized (width*scale) x (height*scale).
    """
    if not HAS_CORESVG:
        raise RuntimeError("CoreSVG framework not available")

    pixel_w = width * scale
    pixel_h = height * scale

    cf_data = _CF.CFDataCreate(None, svg_data, len(svg_data))
    if not cf_data:
        raise RuntimeError("CFDataCreate failed")

    try:
        svg_doc = _CoreSVG.CGSVGDocumentCreateFromData(cf_data, None)
        if not svg_doc:
            raise RuntimeError("CGSVGDocumentCreateFromData failed")

        try:
            kCGImageAlphaPremultipliedFirst = 2
            kCGBitmapByteOrder32Little = 2 << 12
            bitmap_info = (kCGImageAlphaPremultipliedFirst
                           | kCGBitmapByteOrder32Little)

            colorspace = _CG.CGColorSpaceCreateWithName(
                c_void_p.in_dll(_CG, "kCGColorSpaceSRGB"))
            if not colorspace:
                raise RuntimeError("CGColorSpaceCreateWithName failed")

            try:
                bpr = pixel_w * 4
                ctx = _CG.CGBitmapContextCreate(
                    None, pixel_w, pixel_h, 8, bpr, colorspace, bitmap_info)
                if not ctx:
                    raise RuntimeError("CGBitmapContextCreate failed")

                try:
                    if scale > 1:
                        _CG.CGContextScaleCTM(
                            ctx, float(scale), float(scale))
                    _CoreSVG.CGContextDrawSVGDocument(ctx, svg_doc)

                    data_ptr = _CG.CGBitmapContextGetData(ctx)
                    return ctypes.string_at(data_ptr, pixel_w * pixel_h * 4)
                finally:
                    _CG.CGContextRelease(ctx)
            finally:
                _CG.CGColorSpaceRelease(colorspace)
        finally:
            _CF.CFRelease(svg_doc)
    finally:
        _CF.CFRelease(cf_data)
