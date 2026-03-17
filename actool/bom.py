"""
BOM (Bill of Materials) file writer.

BOM is Apple's container format used for .car files, .pkg installers, etc.
All BOM structures use big-endian byte order.
"""

import struct
from typing import Optional


class BOMWriter:
    """Writes BOM format files."""

    def __init__(self):
        self._blocks: list[bytes] = [b""]  # Block 0 is always empty
        self._named_blocks: dict[str, int] = {}
        self._trees: dict[str, int] = {}

    def add_block(self, data: bytes) -> int:
        """Add a block and return its index."""
        idx = len(self._blocks)
        self._blocks.append(data)
        return idx

    def add_named_block(self, name: str, data: bytes) -> int:
        """Add a named block (variable)."""
        idx = self.add_block(data)
        self._named_blocks[name] = idx
        return idx

    def add_tree(self, name: str, entries: list[tuple[bytes, bytes]],
                 block_size: int = 4096) -> int:
        """Add a BOM tree with the given key-value entries.

        entries: list of (key_bytes, value_bytes) pairs.
        Returns the block index of the tree header.
        """
        # Build leaf nodes. Each leaf node can hold up to block_size worth of entries.
        # Entry format in node: value_block_idx(4) + key_block_idx(4) = 8 bytes per entry
        # Node header: isLeaf(2) + count(2) + forward(4) + backward(4) = 12 bytes
        max_entries_per_node = (block_size - 12) // 8

        if len(entries) == 0:
            # Empty tree - single empty leaf node
            node_data = struct.pack(">HHiI", 1, 0, 0, 0)
            node_idx = self.add_block(node_data)
            tree_header = struct.pack(">4sIIIIB", b"tree", 1, node_idx,
                                      block_size, 0, 0)
            tree_idx = self.add_block(tree_header)
            self._named_blocks[name] = tree_idx
            return tree_idx

        # Create leaf nodes
        leaf_nodes = []
        for start in range(0, len(entries), max_entries_per_node):
            batch = entries[start:start + max_entries_per_node]
            leaf_nodes.append(batch)

        if len(leaf_nodes) == 1:
            # Single leaf node - simple case
            node_data = self._build_leaf_node(leaf_nodes[0], 0, 0)
            node_idx = self.add_block(node_data)
            tree_header = struct.pack(">4sIIIIB", b"tree", 1, node_idx,
                                      block_size, len(entries), 0)
            tree_idx = self.add_block(tree_header)
            self._named_blocks[name] = tree_idx
            return tree_idx

        # Multiple leaf nodes - need internal node(s)
        # For simplicity, build a single-level tree with one internal node
        leaf_indices = []
        for i, batch in enumerate(leaf_nodes):
            fwd = 0  # Will be set after we know all indices
            bwd = 0
            node_data = self._build_leaf_node(batch, fwd, bwd)
            leaf_indices.append(self.add_block(node_data))

        # Build internal node
        # Internal node format: isLeaf(2) + count(2) + forward(4) + backward(4)
        # Then: child0(4), [key_block(4) + child(4)] * count
        internal = struct.pack(">HHII", 0, len(leaf_indices) - 1, 0, 0)
        internal += struct.pack(">I", leaf_indices[0])
        for i in range(1, len(leaf_indices)):
            # Key is the first key of this leaf node
            first_key = leaf_nodes[i][0][0]
            key_idx = self.add_block(first_key)
            internal += struct.pack(">II", key_idx, leaf_indices[i])
        internal_idx = self.add_block(internal)

        tree_header = struct.pack(">4sIIIIB", b"tree", 1, internal_idx,
                                  block_size, len(entries), 0)
        tree_idx = self.add_block(tree_header)
        self._named_blocks[name] = tree_idx
        return tree_idx

    def _build_leaf_node(self, entries: list[tuple[bytes, bytes]],
                         forward: int, backward: int) -> bytes:
        """Build a leaf node from entries."""
        node = struct.pack(">HHII", 1, len(entries), forward, backward)
        for key_data, value_data in entries:
            val_idx = self.add_block(value_data)
            key_idx = self.add_block(key_data)
            node += struct.pack(">II", val_idx, key_idx)
        return node

    def write(self, path: str):
        """Write the BOM file to disk."""
        # Calculate block offsets
        header_size = 32  # BOMStore header
        # Start placing blocks after header
        current_offset = header_size

        block_entries = []
        for i, block_data in enumerate(self._blocks):
            if i == 0:
                block_entries.append((0, 0))
                continue
            # Align to 16-byte boundary
            if current_offset % 16 != 0:
                current_offset += 16 - (current_offset % 16)
            block_entries.append((current_offset, len(block_data)))
            current_offset += len(block_data)

        # Build index (block table)
        index_data = struct.pack(">I", len(block_entries))
        for offset, length in block_entries:
            index_data += struct.pack(">II", offset, length)

        # Build vars section
        vars_data = struct.pack(">I", len(self._named_blocks))
        for name, block_idx in self._named_blocks.items():
            name_bytes = name.encode("ascii")
            vars_data += struct.pack(">IB", block_idx, len(name_bytes))
            vars_data += name_bytes

        # Align current_offset for vars
        if current_offset % 16 != 0:
            current_offset += 16 - (current_offset % 16)
        vars_offset = current_offset
        vars_length = len(vars_data)
        current_offset += vars_length

        # Align for index
        if current_offset % 16 != 0:
            current_offset += 16 - (current_offset % 16)
        index_offset = current_offset
        index_length = len(index_data)

        # Write the file
        with open(path, "wb") as f:
            # Header
            f.write(b"BOMStore")
            f.write(struct.pack(">I", 1))  # version
            f.write(struct.pack(">I", len(self._blocks)))  # numberOfBlocks
            f.write(struct.pack(">I", index_offset))
            f.write(struct.pack(">I", index_length))
            f.write(struct.pack(">I", vars_offset))
            f.write(struct.pack(">I", vars_length))

            # Blocks
            for i, block_data in enumerate(self._blocks):
                if i == 0:
                    continue
                expected_offset = block_entries[i][0]
                current_pos = f.tell()
                if current_pos < expected_offset:
                    f.write(b"\x00" * (expected_offset - current_pos))
                f.write(block_data)

            # Vars
            current_pos = f.tell()
            if current_pos < vars_offset:
                f.write(b"\x00" * (vars_offset - current_pos))
            f.write(vars_data)

            # Index
            current_pos = f.tell()
            if current_pos < index_offset:
                f.write(b"\x00" * (index_offset - current_pos))
            f.write(index_data)
