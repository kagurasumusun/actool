"""
Create test xcassets subsets and analyze system actool's atlas packing.
"""

import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path


def create_subset(name, imagesets, src_catalog="test/Images.xcassets"):
    """Create a subset xcassets catalog with selected imagesets."""
    dest = f"test_subsets/{name}.xcassets"
    os.makedirs(dest, exist_ok=True)

    # Copy root Contents.json
    shutil.copy2(f"{src_catalog}/Contents.json", f"{dest}/Contents.json")

    # Copy selected imagesets
    for iset in imagesets:
        src = f"{src_catalog}/{iset}.imageset"
        dst = f"{dest}/{iset}.imageset"
        if os.path.exists(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)

    return dest


def run_actool(xcassets_path, outdir):
    """Run system actool and return the output directory."""
    os.makedirs(outdir, exist_ok=True)
    result = subprocess.run(
        ["/usr/bin/actool", "--compile", outdir,
         "--platform", "macosx",
         "--minimum-deployment-target", "11.0",
         xcassets_path],
        capture_output=True, text=True
    )
    return result


def parse_bom(path):
    """Parse a BOM file."""
    with open(path, 'rb') as f:
        data = f.read()

    idx_off = struct.unpack('>I', data[16:20])[0]
    idx_data = data[idx_off:]
    n = struct.unpack('>I', idx_data[:4])[0]
    blocks = []
    for i in range(n):
        off, ln = struct.unpack('>II', idx_data[4 + i * 8:12 + i * 8])
        blocks.append((off, ln))

    vars_off = struct.unpack('>I', data[24:28])[0]
    vd = data[vars_off:]
    nv = struct.unpack('>I', vd[:4])[0]
    named = {}
    pos = 4
    for _ in range(nv):
        vi = struct.unpack('>I', vd[pos:pos + 4])[0]
        nl = vd[pos + 4]
        nm = vd[pos + 5:pos + 5 + nl].decode()
        named[nm] = vi
        pos += 5 + nl

    return data, blocks, named


def parse_tree_entries(data, blocks, tree_block_idx):
    """Parse BOM tree entries."""
    off, ln = blocks[tree_block_idx]
    tree = data[off:off + ln]
    if tree[:4] != b'tree':
        return []
    child = struct.unpack('>I', tree[8:12])[0]
    entries = []
    _collect_leaves(data, blocks, child, entries)
    return entries


def _collect_leaves(data, blocks, node_idx, entries):
    off, ln = blocks[node_idx]
    node = data[off:off + ln]
    is_leaf = struct.unpack('>H', node[:2])[0]
    count = struct.unpack('>H', node[2:4])[0]
    if is_leaf:
        pos = 12
        for _ in range(count):
            vi = struct.unpack('>I', node[pos:pos + 4])[0]
            ki = struct.unpack('>I', node[pos + 4:pos + 8])[0]
            pos += 8
            koff, kln = blocks[ki]
            voff, vln = blocks[vi]
            entries.append((data[koff:koff + kln], data[voff:voff + vln]))
    else:
        pos = 12
        child0 = struct.unpack('>I', node[pos:pos + 4])[0]
        _collect_leaves(data, blocks, child0, entries)
        pos += 4
        for _ in range(count):
            pos += 4  # skip key
            child = struct.unpack('>I', node[pos:pos + 4])[0]
            pos += 4
            _collect_leaves(data, blocks, child, entries)


def analyze_car(path):
    """Analyze renditions in a CAR file."""
    data, blocks, named = parse_bom(path)
    key_attrs = [7, 13, 1, 2, 3, 17, 8, 9, 11, 12]

    entries = parse_tree_entries(data, blocks, named['RENDITIONS'])

    renditions = []
    for key, val in entries:
        kv = struct.unpack(f'<{len(key)//2}H', key)
        kd = {key_attrs[i]: kv[i] for i in range(min(len(kv), len(key_attrs)))}

        w = struct.unpack('<I', val[12:16])[0]
        h = struct.unpack('<I', val[16:20])[0]
        scale = struct.unpack('<I', val[20:24])[0]
        pf = val[24:28]
        layout = struct.unpack('<H', val[36:38])[0]
        name = val[40:168].split(b'\x00')[0].decode('ascii', errors='replace')
        tvl_len = struct.unpack('<I', val[168:172])[0]
        rend_len = struct.unpack('<I', val[180:184])[0]

        # Parse TLVs for packed image references
        inlk_data = None
        tlv_pos = 184
        while tlv_pos < 184 + tvl_len:
            ttag = struct.unpack('<I', val[tlv_pos:tlv_pos + 4])[0]
            tlen = struct.unpack('<I', val[tlv_pos + 4:tlv_pos + 8])[0]
            if ttag == 0x03f2:
                inlk_data = val[tlv_pos + 8:tlv_pos + 8 + tlen]
            tlv_pos += 8 + tlen

        info = {
            'key': kd, 'width': w, 'height': h, 'scale': scale // 100 if scale else 0,
            'pixel_format': pf, 'layout': layout, 'name': name,
            'rend_len': rend_len, 'csi_size': len(val),
        }

        if inlk_data and len(inlk_data) >= 20:
            # INLK: tag(4) + unk(4) + unk2(4) + x(4) + w(4) + h(4)
            inlk_x = struct.unpack('<I', inlk_data[12:16])[0]
            inlk_w = struct.unpack('<I', inlk_data[16:20])[0]
            inlk_h = struct.unpack('<I', inlk_data[20:24])[0] if len(inlk_data) >= 24 else 0
            info['inlk_x'] = inlk_x
            info['inlk_w'] = inlk_w
            info['inlk_h'] = inlk_h
            info['inlk_raw'] = inlk_data.hex()

        renditions.append(info)

    return renditions


def print_renditions(renditions):
    """Print rendition analysis."""
    packed_assets = [r for r in renditions if r['layout'] == 1004]
    packed_refs = [r for r in renditions if r['layout'] == 1003]
    inline = [r for r in renditions if r['layout'] == 12]
    other = [r for r in renditions if r['layout'] not in (12, 1003, 1004)]

    if packed_assets:
        print(f"\n  PackedAssets (layout=1004): {len(packed_assets)}")
        for r in packed_assets:
            print(f"    {r['name']:40s} {r['width']:4d}x{r['height']:<4d} "
                  f"@{r['scale']}x pf={r['pixel_format']} "
                  f"dim1={r['key'][8]} rend_len={r['rend_len']}")

    if packed_refs:
        print(f"\n  PackedImage refs (layout=1003): {len(packed_refs)}")
        for r in sorted(packed_refs, key=lambda x: (x['scale'], x.get('inlk_x', 0))):
            inlk = ""
            if 'inlk_x' in r:
                inlk = f" atlas_x={r['inlk_x']} atlas_w={r['inlk_w']} atlas_h={r.get('inlk_h', '?')}"
            print(f"    {r['name']:40s} {r['width']:4d}x{r['height']:<4d} "
                  f"@{r['scale']}x pf={r['pixel_format']}{inlk}")

    if inline:
        print(f"\n  Inline images (layout=12): {len(inline)}")
        for r in inline:
            print(f"    {r['name']:40s} {r['width']:4d}x{r['height']:<4d} "
                  f"@{r['scale']}x pf={r['pixel_format']} rend_len={r['rend_len']}")

    if other:
        print(f"\n  Other: {len(other)}")
        for r in other:
            print(f"    {r['name']:40s} layout={r['layout']} {r['width']:4d}x{r['height']:<4d}")


# Define test subsets
TESTS = {
    # Single image tests
    "1_single_rgba": ["Globe"],
    "2_single_la": ["PinTemplate"],
    "3_two_la": ["PinTemplate", "PauseOn"],
    "4_rgba_and_la": ["Globe", "PinTemplate"],
    # Size tests
    "5_large_only": ["CreateLarge"],
    "6_small_only": ["PriorityHighTemplate", "PriorityLowTemplate", "PriorityNormalTemplate"],
    # Mixed sizes
    "7_mixed_sizes": ["Globe", "PinTemplate", "DownloadBadge", "PriorityHighTemplate"],
    # Many small
    "8_many_small": [
        "PinTemplate", "PauseOn", "PauseOff", "PauseHover",
        "RevealOn", "RevealOff", "RevealHover",
        "PriorityHighTemplate", "PriorityLowTemplate", "PriorityNormalTemplate",
    ],
    # All templates
    "9_all_templates": [
        "CleanupTemplate", "DownArrowGroupTemplate", "DownArrowTemplate",
        "EllipsisTemplate", "PinTemplate", "PriorityHighTemplate",
        "PriorityLowTemplate", "PriorityNormalTemplate", "TortoiseTemplate",
        "UpArrowGroupTemplate", "UpArrowTemplate", "YingYangGroupTemplate",
        "YingYangTemplate",
    ],
}


def main():
    # Clean up
    shutil.rmtree("test_subsets", ignore_errors=True)
    shutil.rmtree("test_subset_out", ignore_errors=True)

    for test_name, imagesets in TESTS.items():
        print(f"\n{'='*70}")
        print(f"TEST: {test_name} ({len(imagesets)} imagesets: {', '.join(imagesets[:5])}{'...' if len(imagesets) > 5 else ''})")
        print(f"{'='*70}")

        catalog = create_subset(test_name, imagesets)
        outdir = f"test_subset_out/{test_name}"

        result = run_actool(catalog, outdir)
        if result.returncode != 0:
            print(f"  ERROR: actool failed: {result.stderr}")
            continue

        car_path = f"{outdir}/Assets.car"
        if not os.path.exists(car_path):
            print(f"  ERROR: No Assets.car produced")
            continue

        print(f"  Assets.car size: {os.path.getsize(car_path)} bytes")
        renditions = analyze_car(car_path)
        print_renditions(renditions)


if __name__ == '__main__':
    main()
