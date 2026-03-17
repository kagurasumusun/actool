"""Compare two .car files structurally."""

import struct
import sys


def parse_bom(path):
    with open(path, 'rb') as f:
        data = f.read()

    _, version, num_blocks, idx_off, idx_len, vars_off, vars_len = struct.unpack(
        '>8sIIIIII', data[:32])

    # Parse block table
    idx_data = data[idx_off:idx_off + idx_len]
    n = struct.unpack('>I', idx_data[:4])[0]
    blocks = []
    for i in range(n):
        off, ln = struct.unpack('>II', idx_data[4 + i * 8:12 + i * 8])
        blocks.append((off, ln))

    # Parse vars
    vd = data[vars_off:vars_off + vars_len]
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


def read_block(data, blocks, idx):
    if idx >= len(blocks):
        return None
    off, ln = blocks[idx]
    return data[off:off + ln]


def parse_tree_entries(data, blocks, tree_block_idx):
    tree = read_block(data, blocks, tree_block_idx)
    if not tree or tree[:4] != b'tree':
        return []
    child = struct.unpack('>I', tree[8:12])[0]
    path_count = struct.unpack('>I', tree[16:20])[0]

    entries = []
    _collect_leaf_entries(data, blocks, child, entries)
    return entries


def _collect_leaf_entries(data, blocks, node_idx, entries):
    node = read_block(data, blocks, node_idx)
    if not node:
        return
    is_leaf = struct.unpack('>H', node[:2])[0]
    count = struct.unpack('>H', node[2:4])[0]

    if is_leaf:
        pos = 12
        for _ in range(count):
            vi = struct.unpack('>I', node[pos:pos + 4])[0]
            ki = struct.unpack('>I', node[pos + 4:pos + 8])[0]
            pos += 8
            key = read_block(data, blocks, ki)
            val = read_block(data, blocks, vi)
            entries.append((key, val))
    else:
        pos = 12
        child0 = struct.unpack('>I', node[pos:pos + 4])[0]
        _collect_leaf_entries(data, blocks, child0, entries)
        pos += 4
        for _ in range(count):
            _ki = struct.unpack('>I', node[pos:pos + 4])[0]
            child = struct.unpack('>I', node[pos + 4:pos + 8])[0]
            pos += 8
            _collect_leaf_entries(data, blocks, child, entries)


def parse_carheader(block):
    tag = block[0:4]
    coreui_ver = struct.unpack('<I', block[4:8])[0]
    storage_ver = struct.unpack('<I', block[8:12])[0]
    rend_count = struct.unpack('<I', block[16:20])[0]
    main_ver = block[20:148].split(b'\x00')[0].decode()
    ver_str = block[148:404].split(b'\x00')[0].decode()
    schema = struct.unpack('<I', block[424:428])[0]
    cs = struct.unpack('<I', block[428:432])[0]
    ks = struct.unpack('<I', block[432:436])[0]
    return {
        'tag': tag, 'coreui_version': coreui_ver,
        'storage_version': storage_ver, 'rendition_count': rend_count,
        'main_version': main_ver, 'version_string': ver_str,
        'schema_version': schema, 'colorspace_id': cs, 'key_semantics': ks,
    }


def parse_rendition_key(key_data, key_attrs):
    vals = struct.unpack(f'<{len(key_data)//2}H', key_data)
    return {key_attrs[i]: vals[i] for i in range(min(len(vals), len(key_attrs)))}


def parse_csi_summary(csi):
    w, h = struct.unpack('<II', csi[12:20])
    scale = struct.unpack('<I', csi[20:24])[0]
    pf = csi[24:28]
    layout = struct.unpack('<H', csi[36:38])[0]
    name = csi[40:168].split(b'\x00')[0].decode('ascii', errors='replace')
    tvl_len = struct.unpack('<I', csi[168:172])[0]
    rend_len = struct.unpack('<I', csi[180:184])[0]
    return {
        'width': w, 'height': h, 'scale': scale,
        'pixel_format': pf, 'layout': layout, 'name': name,
        'tvl_length': tvl_len, 'rendition_length': rend_len,
        'total_csi': len(csi),
    }


def compare_cars(path1, path2):
    key_attrs = [7, 13, 1, 2, 3, 17, 8, 9, 11, 12]
    attr_names = {7: 'Appear', 13: 'Unk13', 1: 'Elem', 2: 'Part', 3: 'Size',
                  17: 'ID', 8: 'Dim1', 9: 'Dim2', 11: 'Layer', 12: 'Scale'}

    for path in [path1, path2]:
        data, blocks, named = parse_bom(path)
        print(f'\n=== {path} ===')
        print(f'File size: {len(data)}')
        print(f'Named blocks: {list(named.keys())}')

        # CARHEADER
        ch_idx = named.get('CARHEADER')
        if ch_idx:
            ch = parse_carheader(read_block(data, blocks, ch_idx))
            print(f'CARHEADER: renditions={ch["rendition_count"]}, '
                  f'schema={ch["schema_version"]}, '
                  f'coreui_ver={ch["coreui_version"]}, '
                  f'storage_ver={ch["storage_version"]}')
            print(f'  main_version: {ch["main_version"]}')
            print(f'  version_string: {ch["version_string"]}')

        # FACETKEYS
        fk_idx = named.get('FACETKEYS')
        if fk_idx:
            entries = parse_tree_entries(data, blocks, fk_idx)
            print(f'FACETKEYS: {len(entries)} entries')
            for key, val in sorted(entries, key=lambda e: e[0]):
                name = key.decode('ascii', errors='replace')
                n_attrs = struct.unpack('<H', val[4:6])[0]
                attrs = {}
                for j in range(n_attrs):
                    an, av = struct.unpack('<HH', val[6 + j * 4:10 + j * 4])
                    attrs[an] = av
                print(f'  {name}: elem={attrs.get(1)}, part={attrs.get(2)}, id={attrs.get(17)}')

        # RENDITIONS
        rend_idx = named.get('RENDITIONS')
        if rend_idx:
            entries = parse_tree_entries(data, blocks, rend_idx)
            print(f'RENDITIONS: {len(entries)} entries')
            for key, val in entries[:10]:
                kd = parse_rendition_key(key, key_attrs)
                cs = parse_csi_summary(val)
                kstr = ' '.join(f'{attr_names[k]}={v}' for k, v in kd.items() if v != 0)
                print(f'  [{kstr}] name="{cs["name"]}" {cs["width"]}x{cs["height"]} '
                      f'@{cs["scale"]}x layout={cs["layout"]} csi={cs["total_csi"]}b')


if __name__ == '__main__':
    compare_cars(sys.argv[1], sys.argv[2])
