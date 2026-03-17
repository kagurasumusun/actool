"""Test system actool behavior with localized assets."""

import os
import shutil
import struct
import subprocess
import sys


def run_actool(outdir, extra_args=None):
    os.makedirs(outdir, exist_ok=True)
    cmd = ["/usr/bin/actool", "--compile", outdir,
           "--platform", "macosx", "--minimum-deployment-target", "11.0"]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append("test_l10n/Localized.xcassets")
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result


def count_renditions(car_path):
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

    # Count renditions
    rend_idx = named['RENDITIONS']
    tree_off, tree_ln = blocks[rend_idx]
    tree_hdr = data[tree_off:tree_off + tree_ln]
    child = struct.unpack('>I', tree_hdr[8:12])[0]

    entries = []
    _collect(data, blocks, child, entries)

    # Parse each rendition name
    names = []
    for key, val in entries:
        name = val[40:168].split(b'\x00')[0].decode('ascii', errors='replace')
        names.append(name)
    return len(entries), names


def _collect(data, blocks, node_idx, entries):
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
        _collect(data, blocks, c0, entries)
        pos += 4
        for _ in range(count):
            pos += 4
            c = struct.unpack('>I', node[pos:pos + 4])[0]
            pos += 4
            _collect(data, blocks, c, entries)


tests = [
    ("baseline", []),
    ("dev_en", ["--development-region", "en"]),
    ("dev_fr", ["--development-region", "fr"]),
    ("include_en", ["--include-language", "en"]),
    ("include_fr", ["--include-language", "fr"]),
    ("include_en_fr", ["--include-language", "en", "--include-language", "fr"]),
    ("dev_en_include_fr", ["--development-region", "en", "--include-language", "fr"]),
    ("dev_en_include_en", ["--development-region", "en", "--include-language", "en"]),
]

for label, args in tests:
    outdir = f"test_l10n/out_{label}"
    shutil.rmtree(outdir, ignore_errors=True)
    result = run_actool(outdir, args)
    car = f"{outdir}/Assets.car"
    if os.path.exists(car):
        n, names = count_renditions(car)
        size = os.path.getsize(car)
        print(f"{label:25s}: {n:2d} renditions, {size:6d}b  names={sorted(set(names))}")
    else:
        print(f"{label:25s}: NO OUTPUT  stderr={result.stderr[:100]}")
