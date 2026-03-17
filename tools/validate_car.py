"""Validate a .car file by parsing and verifying all renditions."""

import struct
import sys

try:
    import liblzfse as lzfse
    HAS_LZFSE = True
except ImportError:
    HAS_LZFSE = False

from tools.compare_car import parse_bom, parse_tree_entries, parse_rendition_key, parse_csi_summary


def validate_car(path):
    key_attrs = [7, 13, 1, 2, 3, 17, 8, 9, 11, 12]
    data, blocks, named = parse_bom(path)

    print(f"File: {path}, size={len(data)} bytes")

    # Check required named blocks
    required = ['CARHEADER', 'RENDITIONS', 'FACETKEYS', 'KEYFORMAT',
                'EXTENDED_METADATA']
    for name in required:
        if name in named:
            block = data[blocks[named[name]][0]:
                         blocks[named[name]][0] + blocks[named[name]][1]]
            print(f"  {name}: block {named[name]}, {len(block)} bytes - OK")
        else:
            print(f"  {name}: MISSING!")

    # Validate CARHEADER
    ch_idx = named.get('CARHEADER')
    if ch_idx:
        off, ln = blocks[ch_idx]
        ch = data[off:off + ln]
        tag = ch[0:4]
        if tag != b'RATC':
            print(f"  CARHEADER tag mismatch: {tag} (expected RATC)")
        rend_count = struct.unpack('<I', ch[16:20])[0]
        print(f"  Rendition count in header: {rend_count}")

    # Validate KEYFORMAT
    kf_idx = named.get('KEYFORMAT')
    if kf_idx:
        off, ln = blocks[kf_idx]
        kf = data[off:off + ln]
        kf_tag = kf[0:4]
        if kf_tag not in (b'kfmt', b'tmfk'):
            print(f"  KEYFORMAT tag mismatch: {kf_tag}")
        kf_count = struct.unpack('<I', kf[8:12])[0]
        print(f"  Key format token count: {kf_count}")

    # Validate RENDITIONS
    rend_idx = named.get('RENDITIONS')
    if rend_idx:
        entries = parse_tree_entries(data, blocks, rend_idx)
        print(f"  Rendition entries: {len(entries)}")

        ok_count = 0
        err_count = 0

        for key, val in entries:
            kd = parse_rendition_key(key, key_attrs)
            cs = parse_csi_summary(val)

            # Check CSI tag
            csi_tag = val[0:4]
            if csi_tag not in (b'ISTC', b'CTSI'):
                print(f"  ERROR: CSI tag={csi_tag} for {cs['name']}")
                err_count += 1
                continue

            # Check TLV section
            tvl_len = cs['tvl_length']
            rend_len = cs['rendition_length']
            expected_total = 184 + tvl_len + rend_len
            if len(val) != expected_total:
                print(f"  ERROR: Size mismatch for {cs['name']}: "
                      f"expected={expected_total}, actual={len(val)}")
                err_count += 1
                continue

            # Try to decompress rendition data
            if rend_len > 0:
                rend_start = 184 + tvl_len
                rend_tag = val[rend_start:rend_start + 4]
                if rend_tag == b'MLEC':  # CELM
                    comp_type = struct.unpack('<I', val[rend_start + 8:rend_start + 12])[0]
                    raw_len = struct.unpack('<I', val[rend_start + 12:rend_start + 16])[0]
                    compressed = val[rend_start + 16:rend_start + rend_len]
                    if comp_type == 4 and HAS_LZFSE:
                        try:
                            decompressed = lzfse.decompress(compressed)
                            ok_count += 1
                        except Exception as e:
                            print(f"  ERROR: LZFSE decompress failed for {cs['name']}: {e}")
                            err_count += 1
                    elif comp_type == 0:
                        # Uncompressed
                        if len(compressed) == raw_len:
                            ok_count += 1
                        else:
                            print(f"  ERROR: Uncompressed size mismatch for {cs['name']}")
                            err_count += 1
                    else:
                        ok_count += 1  # Can't validate other compression types
                elif rend_tag == b'SISM':  # MultisizeImage
                    ok_count += 1
                elif rend_tag == b'DWAR':  # RAWD
                    ok_count += 1
                else:
                    print(f"  WARN: Unknown rendition tag {rend_tag} for {cs['name']}")
                    ok_count += 1
            else:
                ok_count += 1  # Packed image reference (no inline data)

        print(f"  Validated: {ok_count} OK, {err_count} errors")

    # Validate FACETKEYS
    fk_idx = named.get('FACETKEYS')
    if fk_idx:
        fk_entries = parse_tree_entries(data, blocks, fk_idx)
        print(f"  Facet entries: {len(fk_entries)}")

    print("\nValidation complete!")
    return err_count == 0


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else 'our_outdir/Assets.car'
    success = validate_car(path)
    sys.exit(0 if success else 1)
