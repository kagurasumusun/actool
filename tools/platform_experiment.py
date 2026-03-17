"""
Test system actool with different platform targets and deployment versions.
Compare output structures to find behavioural differences.
"""

import os
import shutil
import struct
import subprocess
import sys
import json


def run_actool(xcassets_path, outdir, platform, min_deploy, app_icon=None):
    """Run system actool with given platform settings."""
    os.makedirs(outdir, exist_ok=True)
    cmd = [
        "/usr/bin/actool", "--compile", outdir,
        "--platform", platform,
        "--minimum-deployment-target", min_deploy,
    ]
    if app_icon:
        cmd += ["--app-icon", app_icon,
                "--output-partial-info-plist", f"{outdir}/AppIcon.Info.plist"]
    cmd.append(xcassets_path)

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result


def parse_bom(path):
    with open(path, 'rb') as f:
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
    return data, blocks, named


def collect_leaves(data, blocks, node_idx, entries):
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
        c0 = struct.unpack('>I', node[pos:pos + 4])[0]
        collect_leaves(data, blocks, c0, entries)
        pos += 4
        for _ in range(count):
            pos += 4
            c = struct.unpack('>I', node[pos:pos + 4])[0]
            pos += 4
            collect_leaves(data, blocks, c, entries)


def analyze_car(path):
    """Analyze key properties of a CAR file."""
    data, blocks, named = parse_bom(path)

    info = {
        'file_size': len(data),
        'named_blocks': list(named.keys()),
    }

    # CARHEADER
    ch_idx = named.get('CARHEADER')
    if ch_idx:
        off, ln = blocks[ch_idx]
        ch = data[off:off + ln]
        info['coreui_version'] = struct.unpack('<I', ch[4:8])[0]
        info['storage_version'] = struct.unpack('<I', ch[8:12])[0]
        info['rendition_count'] = struct.unpack('<I', ch[16:20])[0]
        info['schema_version'] = struct.unpack('<I', ch[424:428])[0]
        info['colorspace_id'] = struct.unpack('<I', ch[428:432])[0]
        info['key_semantics'] = struct.unpack('<I', ch[432:436])[0]

    # KEYFORMAT
    kf_idx = named.get('KEYFORMAT')
    if kf_idx:
        off, ln = blocks[kf_idx]
        kf = data[off:off + ln]
        kf_count = struct.unpack('<I', kf[8:12])[0]
        tokens = []
        for i in range(kf_count):
            tokens.append(struct.unpack('<I', kf[12 + i * 4:16 + i * 4])[0])
        info['keyformat_tokens'] = tokens

    # EXTENDED_METADATA
    em_idx = named.get('EXTENDED_METADATA')
    if em_idx:
        off, ln = blocks[em_idx]
        em = data[off:off + ln]
        info['deploy_version'] = em[260:516].split(b'\x00')[0].decode()
        info['deploy_platform'] = em[516:772].split(b'\x00')[0].decode()

    # RENDITIONS
    rend_idx = named.get('RENDITIONS')
    if rend_idx:
        tree_off, tree_ln = blocks[rend_idx]
        tree_hdr = data[tree_off:tree_off + tree_ln]
        child = struct.unpack('>I', tree_hdr[8:12])[0]
        entries = []
        collect_leaves(data, blocks, child, entries)
        info['rendition_count_actual'] = len(entries)

        layouts = {}
        pixel_formats = {}
        for key, val in entries:
            layout = struct.unpack('<H', val[36:38])[0]
            pf = val[24:28]
            layouts[layout] = layouts.get(layout, 0) + 1
            pf_str = pf.decode('ascii', errors='replace').strip()
            pixel_formats[pf_str] = pixel_formats.get(pf_str, 0) + 1
        info['layouts'] = layouts
        info['pixel_formats'] = pixel_formats

    # Check for additional named blocks
    info['has_appearancekeys'] = 'APPEARANCEKEYS' in named
    info['has_globals'] = 'CARGLOBALS' in named

    return info


def main():
    xcassets = "test/Images.xcassets"
    base_out = "test_platform_out"
    shutil.rmtree(base_out, ignore_errors=True)

    # Test matrix: (platform, min_deploy, app_icon)
    tests = [
        # macOS versions
        ("macosx", "10.13", "AppIcon"),
        ("macosx", "11.0", "AppIcon"),
        ("macosx", "12.0", "AppIcon"),
        ("macosx", "13.0", "AppIcon"),
        ("macosx", "14.0", "AppIcon"),
        ("macosx", "15.0", "AppIcon"),
        # iOS
        ("iphoneos", "13.0", None),
        ("iphoneos", "15.0", None),
        # Without app icon
        ("macosx", "11.0", None),
        ("macosx", "15.0", None),
    ]

    results = {}
    for platform, deploy, app_icon in tests:
        label = f"{platform}-{deploy}" + (f"-icon" if app_icon else "")
        outdir = f"{base_out}/{label}"
        print(f"\n{'='*60}")
        print(f"TEST: {label}")
        print(f"{'='*60}")

        result = run_actool(xcassets, outdir, platform, deploy, app_icon)
        if result.returncode != 0:
            print(f"  FAILED: {result.stderr[:200]}")
            continue

        car_path = f"{outdir}/Assets.car"
        if not os.path.exists(car_path):
            print(f"  No Assets.car produced")
            continue

        info = analyze_car(car_path)
        results[label] = info

        print(f"  File size: {info['file_size']}")
        print(f"  Named blocks: {info['named_blocks']}")
        print(f"  CoreUI ver: {info.get('coreui_version')}, "
              f"Storage ver: {info.get('storage_version')}, "
              f"Schema: {info.get('schema_version')}")
        print(f"  Key semantics: {info.get('key_semantics')}")
        print(f"  Keyformat tokens: {info.get('keyformat_tokens')}")
        print(f"  Renditions: {info.get('rendition_count_actual')}")
        print(f"  Layouts: {info.get('layouts')}")
        print(f"  Pixel formats: {info.get('pixel_formats')}")
        print(f"  Deploy: {info.get('deploy_platform')} {info.get('deploy_version')}")
        print(f"  APPEARANCEKEYS: {info.get('has_appearancekeys')}")
        print(f"  CARGLOBALS: {info.get('has_globals')}")

        # Check for output files
        files = os.listdir(outdir)
        print(f"  Output files: {files}")

    # Summary of differences
    print(f"\n{'='*60}")
    print("COMPARISON SUMMARY")
    print(f"{'='*60}")

    # Compare key properties across tests
    props = ['rendition_count_actual', 'schema_version', 'key_semantics',
             'coreui_version', 'storage_version']
    for prop in props:
        vals = {k: v.get(prop) for k, v in results.items()}
        unique = set(str(v) for v in vals.values())
        if len(unique) > 1:
            print(f"\n  {prop} VARIES:")
            for k, v in vals.items():
                print(f"    {k}: {v}")
        else:
            print(f"  {prop}: constant = {list(vals.values())[0] if vals else '?'}")

    # Compare keyformat tokens
    token_sets = {k: str(v.get('keyformat_tokens')) for k, v in results.items()}
    unique_tokens = set(token_sets.values())
    if len(unique_tokens) > 1:
        print(f"\n  keyformat_tokens VARIES:")
        for k, v in token_sets.items():
            print(f"    {k}: {v}")

    # Compare layouts
    layout_sets = {k: str(v.get('layouts')) for k, v in results.items()}
    unique_layouts = set(layout_sets.values())
    if len(unique_layouts) > 1:
        print(f"\n  layouts VARIES:")
        for k, v in layout_sets.items():
            print(f"    {k}: {v}")

    # Compare named blocks
    block_sets = {k: str(sorted(v.get('named_blocks', [])))
                  for k, v in results.items()}
    unique_blocks = set(block_sets.values())
    if len(unique_blocks) > 1:
        print(f"\n  named_blocks VARIES:")
        for k, v in block_sets.items():
            print(f"    {k}: {v}")


if __name__ == '__main__':
    main()
