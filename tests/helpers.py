"""Shared test helpers for actool tests."""

import json
import os
import shutil
import struct
import tempfile

from PIL import Image

REF_SAMPLES = os.path.join(os.path.dirname(__file__), "ref_samples")
REF_XCASSETS = os.path.join(REF_SAMPLES, "Catalog.xcassets")
REF_CAR = os.path.join(REF_SAMPLES, "ref_output", "Assets.car")
REF_PLIST = os.path.join(REF_SAMPLES, "ref_output", "AppIcon.Info.plist")
ASSETUTIL = "/usr/bin/assetutil"


def has_assetutil():
    return os.path.isfile(ASSETUTIL) and os.access(ASSETUTIL, os.X_OK)


def has_ref_car():
    return os.path.isfile(REF_CAR)


def make_temp_catalog(imagesets, tmpdir=None):
    """Create a temporary xcassets catalog.

    imagesets: list of (name, mode) where mode is 'RGBA' or 'LA'.
    Returns (catalog_path, tmpdir).
    """
    if tmpdir is None:
        tmpdir = tempfile.mkdtemp(prefix="actool_test_")
    catalog = os.path.join(tmpdir, "Test.xcassets")
    os.makedirs(catalog, exist_ok=True)

    with open(os.path.join(catalog, "Contents.json"), "w") as f:
        json.dump({"info": {"author": "xcode", "version": 1}}, f)

    for name, mode in imagesets:
        iset = os.path.join(catalog, f"{name}.imageset")
        os.makedirs(iset, exist_ok=True)

        if mode == "RGBA":
            color = (200, 100, 50, 255)
        else:
            color = (128, 255)

        Image.new(mode, (16, 16), color).save(os.path.join(iset, f"{name}.png"))
        Image.new(mode, (32, 32), color).save(os.path.join(iset, f"{name}@2x.png"))

        with open(os.path.join(iset, "Contents.json"), "w") as f:
            json.dump({
                "images": [
                    {"filename": f"{name}.png", "idiom": "mac", "scale": "1x"},
                    {"filename": f"{name}@2x.png", "idiom": "mac", "scale": "2x"},
                ],
                "info": {"author": "xcode", "version": 1},
            }, f)

    return catalog, tmpdir


def parse_car_layouts(car_path):
    """Parse a CAR file and return {rendition_name: layout_type}.

    Note: names may not be unique (e.g., packed assets share names).
    Use parse_car_info()['layout_counts'] for accurate counting.
    """
    with open(car_path, 'rb') as f:
        data = f.read()

    idx_off = struct.unpack('>I', data[16:20])[0]
    idx_data = data[idx_off:]
    n = struct.unpack('>I', idx_data[:4])[0]
    blocks = []
    for i in range(n):
        off, ln = struct.unpack('>II', idx_data[4 + i * 8:12 + i * 8])
        blocks.append((off, ln))

    vars_off, vars_ln = struct.unpack('>II', data[24:32])
    vd = data[vars_off:vars_off + vars_ln]
    nv = struct.unpack('>I', vd[:4])[0]
    named = {}
    p = 4
    for _ in range(nv):
        vi = struct.unpack('>I', vd[p:p + 4])[0]
        nl = vd[p + 4]
        nm = vd[p + 5:p + 5 + nl].decode()
        named[nm] = vi
        p += 5 + nl

    rend_idx = named['RENDITIONS']
    tree_off, tree_ln = blocks[rend_idx]
    tree_hdr = data[tree_off:tree_off + tree_ln]
    child = struct.unpack('>I', tree_hdr[8:12])[0]

    results = {}

    def collect(node_idx):
        off, ln = blocks[node_idx]
        node = data[off:off + ln]
        is_leaf = struct.unpack('>H', node[:2])[0]
        count = struct.unpack('>H', node[2:4])[0]
        if is_leaf:
            pos = 12
            for _ in range(count):
                vi = struct.unpack('>I', node[pos:pos + 4])[0]
                pos += 8
                voff, vln = blocks[vi]
                val = data[voff:voff + vln]
                name = val[40:168].split(b'\x00')[0].decode('ascii', errors='replace')
                layout = struct.unpack('<H', val[36:38])[0]
                results[name] = layout
        else:
            pos = 12
            c0 = struct.unpack('>I', node[pos:pos + 4])[0]
            collect(c0)
            pos += 4
            for _ in range(count):
                pos += 4
                c = struct.unpack('>I', node[pos:pos + 4])[0]
                pos += 4
                collect(c)

    collect(child)
    return results


def parse_car_info(car_path):
    """Parse key structural info from a CAR file."""
    with open(car_path, 'rb') as f:
        data = f.read()

    info = {"file_size": len(data)}

    idx_off = struct.unpack('>I', data[16:20])[0]
    idx_data = data[idx_off:]
    n = struct.unpack('>I', idx_data[:4])[0]
    blocks = []
    for i in range(n):
        off, ln = struct.unpack('>II', idx_data[4 + i * 8:12 + i * 8])
        blocks.append((off, ln))

    info["num_blocks"] = struct.unpack('>I', data[12:16])[0]
    info["table_count"] = n

    vars_off, vars_ln = struct.unpack('>II', data[24:32])
    vd = data[vars_off:vars_off + vars_ln]
    nv = struct.unpack('>I', vd[:4])[0]
    named = {}
    p = 4
    for _ in range(nv):
        vi = struct.unpack('>I', vd[p:p + 4])[0]
        nl = vd[p + 4]
        nm = vd[p + 5:p + 5 + nl].decode()
        named[nm] = vi
        p += 5 + nl
    info["named_blocks"] = sorted(named.keys())

    # KEYFORMAT
    if "KEYFORMAT" in named:
        kf_off, kf_ln = blocks[named["KEYFORMAT"]]
        kf = data[kf_off:kf_off + kf_ln]
        kf_count = struct.unpack('<I', kf[8:12])[0]
        info["keyformat_count"] = kf_count

    # Rendition count
    if "RENDITIONS" in named:
        r_off, r_ln = blocks[named["RENDITIONS"]]
        r_hdr = data[r_off:r_off + r_ln]
        if r_hdr[:4] == b'tree':
            info["rendition_count"] = struct.unpack('>I', r_hdr[16:20])[0]

    # BITMAPKEYS count
    if "BITMAPKEYS" in named:
        bk_off, bk_ln = blocks[named["BITMAPKEYS"]]
        bk_hdr = data[bk_off:bk_off + bk_ln]
        if bk_hdr[:4] == b'tree':
            info["bitmapkeys_count"] = struct.unpack('>I', bk_hdr[16:20])[0]

    # Layout counts (from tree entries, not deduplicated names)
    if "RENDITIONS" in named:
        r_idx = named["RENDITIONS"]
        r_off, r_ln = blocks[r_idx]
        r_hdr = data[r_off:r_off + r_ln]
        if r_hdr[:4] == b'tree':
            r_child = struct.unpack('>I', r_hdr[8:12])[0]
            all_layouts = []

            def _count_layouts(ni):
                no, nl = blocks[ni]
                nd = data[no:no + nl]
                il = struct.unpack('>H', nd[:2])[0]
                nc = struct.unpack('>H', nd[2:4])[0]
                if il:
                    p = 12
                    for _ in range(nc):
                        vi = struct.unpack('>I', nd[p:p + 4])[0]
                        p += 8
                        vo, vl = blocks[vi]
                        v = data[vo:vo + vl]
                        all_layouts.append(struct.unpack('<H', v[36:38])[0])
                else:
                    p = 12
                    c0 = struct.unpack('>I', nd[p:p + 4])[0]
                    _count_layouts(c0)
                    p += 4
                    for _ in range(nc):
                        p += 4
                        c = struct.unpack('>I', nd[p:p + 4])[0]
                        p += 4
                        _count_layouts(c)

            _count_layouts(r_child)
            layout_counts = {}
            for l in all_layouts:
                layout_counts[l] = layout_counts.get(l, 0) + 1
            info["layout_counts"] = layout_counts

    return info


def run_assetutil(car_path):
    """Run assetutil -I and return parsed JSON, or None if unavailable."""
    if not has_assetutil():
        return None
    import subprocess
    # assetutil requires relative paths (sandboxed filesystem)
    rel_path = os.path.relpath(car_path)
    result = subprocess.run(
        [ASSETUTIL, "-I", rel_path],
        capture_output=True, text=True, timeout=30)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        import json
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


ASSETUTIL_TMPDIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                 "_test_output")


def get_test_outdir(name):
    """Get a clean test output directory that assetutil can read."""
    outdir = os.path.join(ASSETUTIL_TMPDIR, name)
    if os.path.exists(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)
    return outdir


def cleanup_test_outputs():
    """Remove all test output directories."""
    if os.path.exists(ASSETUTIL_TMPDIR):
        shutil.rmtree(ASSETUTIL_TMPDIR)
