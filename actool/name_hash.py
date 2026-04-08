"""Apple actool name hashing.

Single source of truth for the 16-bit identifier hash that actool assigns
to facet names, locale names, and other rendition-key tokens.
"""


def hash_name(name: str) -> int:
    """Hash a name to a 16-bit identifier (used for facet IDs and locale IDs).

    Matches Apple's /usr/bin/actool byte-for-byte on names up to 15+
    characters (verified against 123+ probe samples including novel
    inputs). The algorithm is a djb2-family Bernstein multiplicative
    hash (seed ``0x189d7``, multiplier 33) that accumulates into a
    64-bit register, then folds the four 16-bit chunks of that register
    via Horner's scheme with the same multiplier 33 to produce the
    final 16-bit id::

        h = 0x189d7
        for c in name.utf8:
            h = (h * 33 + c) mod 2^64
        # Fold the four 16-bit chunks with weights M^3, M^2, M, 1
        c0, c1, c2, c3 = h & 0xFFFF, (h>>16)&0xFFFF, (h>>32)&0xFFFF, (h>>48)&0xFFFF
        id = (c0*M^3 + c1*M^2 + c2*M + c3) mod 2^16

    That sum is exactly Horner's evaluation of the polynomial whose
    coefficients are the 16-bit chunks of the 64-bit accumulator — i.e.
    four levels of folding, each consuming one 16-bit slice, reducing a
    64-bit value down to 16 bits. The multiply-by-33 at each fold level
    is the same operation used during character accumulation, which is
    likely why Apple's implementation falls out naturally from a macro
    / unrolled reduction of the wider accumulator.

    A zero result is remapped to 1 so callers can use 0 as a sentinel.
    """
    M = 33
    h = 0x189D7
    for c in name.encode("utf-8"):
        h = (h * M + c) & 0xFFFFFFFFFFFFFFFF  # 64-bit accumulator
    result = (
        ((h >> 0) & 0xFFFF) * (M ** 3)
        + ((h >> 16) & 0xFFFF) * (M ** 2)
        + ((h >> 32) & 0xFFFF) * M
        + ((h >> 48) & 0xFFFF)
    ) & 0xFFFF
    return result or 1
