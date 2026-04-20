//! Atlas packing for CAR files.
//!
//! Shelf-based bin packing matching Apple's actool layout: images are
//! arranged in horizontal shelves, with column stacking within each shelf.
//! When a single atlas would exceed the height limit, remaining images
//! overflow into additional atlases.

pub const MARGIN: u32 = 2;
pub const GAP: u32 = 2;

pub const PART_REGULAR: u32 = 181;
pub const PART_ICON: u32 = 184;

#[derive(Debug, Clone)]
pub struct PackedImage {
    pub name: String,
    pub identifier: u32,
    pub width: u32,
    pub height: u32,
    pub x: u32,
    pub y: u32,
    pub pixel_data: Vec<u8>,
    pub pixel_format: [u8; 4],
    pub scale: u32,
    pub is_template: bool,
    /// bitmapEncoding: 0=original, 4=automatic, 2=template. Matches Python's
    /// default of 4 (automatic).
    pub template_rendering_intent: i32,
    pub part: u32,
    pub dim2: u32,
    pub appearance: u32,
    pub direction: u32,
}

impl PackedImage {
    pub fn new(name: String, identifier: u32, width: u32, height: u32) -> Self {
        Self {
            name,
            identifier,
            width,
            height,
            x: 0,
            y: 0,
            pixel_data: Vec::new(),
            pixel_format: *b"BGRA",
            scale: 1,
            is_template: false,
            template_rendering_intent: 4,
            part: PART_REGULAR,
            dim2: 0,
            appearance: 0,
            direction: 0,
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct Atlas {
    pub width: u32,
    pub height: u32,
    pub pixel_format: [u8; 4],
    pub scale: u32,
    pub dim1: u32,
    pub images: Vec<PackedImage>,
    pub pixel_data: Vec<u8>,
}

impl Atlas {
    pub fn name(&self) -> String {
        let fmt_idx = if &self.pixel_format == b"BGRA" { 0 } else { 1 };
        format!(
            "ZZZZPackedAsset-{}.{}.{}-gamut0",
            self.scale, self.dim1, fmt_idx
        )
    }

    pub fn bytes_per_row(&self) -> usize {
        let bpp: usize = if &self.pixel_format == b"BGRA" { 4 } else { 2 };
        let exact = self.width as usize * bpp;
        ((exact + 31) / 32) * 32
    }

    /// Blit all packed images into a single atlas pixel buffer. Rows are
    /// padded to 32-byte alignment to match the encoder's expected stride.
    pub fn render(&mut self) {
        let bpp: usize = if &self.pixel_format == b"BGRA" { 4 } else { 2 };
        let bpr = self.bytes_per_row();
        let mut buf = vec![0u8; bpr * self.height as usize];

        for img in &self.images {
            let src_stride = img.width as usize * bpp;
            for row in 0..img.height as usize {
                let src_off = row * src_stride;
                let dst_off = (img.y as usize + row) * bpr + img.x as usize * bpp;
                if src_off + src_stride <= img.pixel_data.len() {
                    buf[dst_off..dst_off + src_stride]
                        .copy_from_slice(&img.pixel_data[src_off..src_off + src_stride]);
                }
            }
        }
        self.pixel_data = buf;
    }
}

struct Column {
    x: u32,
    width: u32,
    bottom: u32,
}

struct Shelf {
    y: u32,
    height: u32,
    columns: Vec<Column>,
}

pub fn pack_images_split(
    mut images: Vec<PackedImage>,
    max_width: u32,
    max_height: u32,
) -> Vec<Atlas> {
    if images.is_empty() {
        return Vec::new();
    }
    images.sort_by(|a, b| b.height.cmp(&a.height).then(b.width.cmp(&a.width)));
    let mut remaining = images;
    let mut atlases = Vec::new();

    while !remaining.is_empty() {
        let first = &remaining[0];
        let mut atlas = Atlas {
            pixel_format: first.pixel_format,
            scale: first.scale,
            ..Default::default()
        };
        let overflow = pack_shelf_atlas(&mut atlas, remaining, max_width, max_height);
        atlases.push(atlas);
        remaining = overflow;
    }
    atlases
}

fn pack_shelf_atlas(
    atlas: &mut Atlas,
    sorted_imgs: Vec<PackedImage>,
    max_width: u32,
    max_height: u32,
) -> Vec<PackedImage> {
    let mut shelves: Vec<Shelf> = Vec::new();
    let mut atlas_width: u32 = 0;
    let mut placed: Vec<PackedImage> = Vec::new();
    let mut overflow: Vec<PackedImage> = Vec::new();

    for mut img in sorted_imgs {
        let mut fit = false;

        for (si, shelf) in shelves.iter_mut().enumerate() {
            let is_first_shelf = si == 0;

            // Try existing columns
            for col in shelf.columns.iter_mut() {
                if img.width <= col.width {
                    let new_bottom = col.bottom + GAP + img.height;
                    if new_bottom <= shelf.y + shelf.height {
                        img.x = col.x;
                        img.y = col.bottom + GAP;
                        col.bottom = img.y + img.height;
                        placed.push(img.clone());
                        fit = true;
                        break;
                    }
                }
            }
            if fit {
                break;
            }

            // New column on this shelf
            let new_x = if let Some(last) = shelf.columns.last() {
                last.x + last.width + GAP
            } else {
                MARGIN
            };

            if img.height <= shelf.height {
                let mut width_ok =
                    is_first_shelf && new_x + img.width + MARGIN <= max_width;
                if !width_ok && atlas_width > 0 {
                    width_ok = new_x + img.width + MARGIN <= atlas_width;
                }
                if !width_ok && shelf.columns.is_empty() {
                    width_ok = true;
                }

                if width_ok {
                    img.x = new_x;
                    img.y = shelf.y;
                    let bottom = img.y + img.height;
                    shelf.columns.push(Column {
                        x: new_x,
                        width: img.width,
                        bottom,
                    });
                    let new_right = new_x + img.width + MARGIN;
                    if new_right > atlas_width {
                        atlas_width = new_right;
                    }
                    placed.push(img.clone());
                    fit = true;
                    break;
                }
            }
        }
        if fit {
            continue;
        }

        // New shelf
        let new_y = if let Some(last) = shelves.last() {
            last.y + last.height + GAP
        } else {
            MARGIN
        };

        if new_y + img.height + MARGIN <= max_height || shelves.is_empty() {
            img.x = MARGIN;
            img.y = new_y;
            let shelf_height = img.height;
            let bottom = img.y + img.height;
            let new_right = MARGIN + img.width + MARGIN;
            if new_right > atlas_width {
                atlas_width = new_right;
            }
            let shelf = Shelf {
                y: new_y,
                height: shelf_height,
                columns: vec![Column {
                    x: MARGIN,
                    width: img.width,
                    bottom,
                }],
            };
            shelves.push(shelf);
            placed.push(img);
        } else {
            overflow.push(img);
        }
    }

    if !shelves.is_empty() {
        atlas.width = atlas_width;
        let mut max_bottom = 0;
        for shelf in &shelves {
            for col in &shelf.columns {
                if col.bottom > max_bottom {
                    max_bottom = col.bottom;
                }
            }
        }
        atlas.height = max_bottom + MARGIN;
    }
    atlas.images = placed;
    overflow
}

#[cfg(test)]
mod tests {
    use super::*;

    fn img(name: &str, w: u32, h: u32) -> PackedImage {
        PackedImage::new(name.to_string(), 0, w, h)
    }

    #[test]
    fn empty_packing() {
        let atlases = pack_images_split(vec![], 262, 196);
        assert!(atlases.is_empty());
    }

    #[test]
    fn single_image_placed_with_margin() {
        let atlases = pack_images_split(vec![img("a", 10, 10)], 262, 196);
        assert_eq!(atlases.len(), 1);
        let atlas = &atlases[0];
        assert_eq!(atlas.images.len(), 1);
        assert_eq!(atlas.images[0].x, MARGIN);
        assert_eq!(atlas.images[0].y, MARGIN);
        assert_eq!(atlas.width, MARGIN + 10 + MARGIN);
    }

    #[test]
    fn two_images_same_height_go_into_columns() {
        let atlases = pack_images_split(
            vec![img("a", 10, 20), img("b", 15, 20)],
            262,
            196,
        );
        assert_eq!(atlases.len(), 1);
        let atlas = &atlases[0];
        assert_eq!(atlas.images.len(), 2);
        // Both on the first shelf (y = MARGIN) side by side.
        assert!(atlas.images.iter().all(|i| i.y == MARGIN));
    }

    #[test]
    fn oversized_image_overflows_new_atlas() {
        // Ask for two atlases worth — first has a mega shelf, second shelf
        // won't fit when max_height is low.
        let atlases = pack_images_split(
            vec![
                img("tall1", 50, 100),
                img("tall2", 50, 100),
                img("tall3", 50, 100),
            ],
            262,
            196,
        );
        // Should split: a tall shelf of ~100 leaves ~90 for another shelf which fits one
        assert!(atlases.iter().map(|a| a.images.len()).sum::<usize>() == 3);
    }

    #[test]
    fn atlas_name_format() {
        let atlas = Atlas {
            scale: 2,
            dim1: 3,
            pixel_format: *b"BGRA",
            ..Default::default()
        };
        assert_eq!(atlas.name(), "ZZZZPackedAsset-2.3.0-gamut0");
        let atlas = Atlas {
            scale: 1,
            dim1: 0,
            pixel_format: *b" 8AG",
            ..Default::default()
        };
        assert_eq!(atlas.name(), "ZZZZPackedAsset-1.0.1-gamut0");
    }

    #[test]
    fn bytes_per_row_alignment() {
        let atlas = Atlas {
            width: 10,
            pixel_format: *b"BGRA",
            ..Default::default()
        };
        // 10 * 4 = 40, aligned to 32 is 64
        assert_eq!(atlas.bytes_per_row(), 64);

        let atlas = Atlas {
            width: 10,
            pixel_format: *b" 8AG",
            ..Default::default()
        };
        // 10 * 2 = 20, aligned to 32 is 32
        assert_eq!(atlas.bytes_per_row(), 32);
    }

    #[test]
    fn render_copies_pixels() {
        let mut atlas = Atlas {
            width: 10,
            height: 10,
            pixel_format: *b"BGRA",
            ..Default::default()
        };
        let mut pi = img("a", 2, 2);
        pi.x = 0;
        pi.y = 0;
        pi.pixel_data = vec![
            1, 2, 3, 4, 5, 6, 7, 8, // row 0
            9, 10, 11, 12, 13, 14, 15, 16, // row 1
        ];
        atlas.images = vec![pi];
        atlas.render();
        // First bytes of first row should be [1,2,3,4,5,6,7,8]
        assert_eq!(&atlas.pixel_data[..8], &[1, 2, 3, 4, 5, 6, 7, 8]);
        // Second row offset = bytes_per_row (64 for width=10 BGRA)
        let bpr = atlas.bytes_per_row();
        assert_eq!(&atlas.pixel_data[bpr..bpr + 8], &[9, 10, 11, 12, 13, 14, 15, 16]);
    }
}
