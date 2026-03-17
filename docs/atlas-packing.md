# Apple actool Atlas Packing - Reverse Engineering Notes

## Overview

Apple's `actool` packs small images into atlas textures to reduce the number
of individual renditions in the CAR file. This document describes the packing
algorithm based on analysis of system actool output.

## Grouping Rules

1. **Format grouping**: Images are grouped by pixel format (BGRA vs GA8)
2. **Scale grouping**: Separate atlas per scale (@1x, @2x)
3. **Icon separation**: App icon images (Part=220) are packed into a separate
   atlas group from regular images (Part=181)
4. **Minimum threshold**: At least 2 images per group to trigger packing.
   Single images are stored inline (layout=12)
5. **Large icon threshold**: App icon images >= 256x256 pixels are stored
   inline, not packed

## Atlas Structure

Each atlas group produces:
- A **PackedAsset** rendition (layout=1004) containing the compressed atlas
  texture. Uses Element=9 (packed asset element), Part=181.
- **PackedImage** references (layout=1003) for each image, containing an
  INLK TLV with position/size in the atlas.

## Packing Algorithm

Column-based bin packing:
- 2px margin on all edges
- 2px gap between images
- Images sorted by height descending, then width descending
- Images stacked vertically in columns
- When image doesn't fit in existing column, start new column

## INLK TLV Format (0x03F2)

```
Offset  Size  Description
0       4     Tag: 'KLNI' (LE uint32 of 'INLK')
4       4     Version: 0
8       4     X offset in atlas (LE uint32)
12      4     Y offset in atlas (LE uint32)
16      4     Width (LE uint32)
20      4     Height (LE uint32)
24+     var   Trailing: stride info + rendition key attributes
```

The trailing bytes contain:
- Stride/bytesPerRow info (varies)
- Rendition key attribute pairs for the PackedAsset (Element=9, Part=181, Scale, etc.)

## Atlas Naming

Format: `ZZZZPackedAsset-{scale}.0.{format_idx}-gamut0`
- scale: 1 for @1x, 2 for @2x
- format_idx: 0 for BGRA, 1 for GA8

## dim1 Mapping

PackedAsset renditions use dim1 to identify the atlas group:
- dim1=0: First BGRA group (regular images)
- dim1=1: Second BGRA group (icon images)
- dim1=2: GA8 group

dim1 increments sequentially across all format groups.
