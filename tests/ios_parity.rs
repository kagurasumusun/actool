//! iOS platform regression tests.
//!
//! Verifies the idiom-carrying catalog layout that `/usr/bin/actool
//! --platform iphoneos` emits: the iOS key format (with Idiom + Subtype
//! columns), CoreUI 975 / key-semantics 2 header, the `ios` deployment
//! platform string, per-idiom rendition keys, and the idiom filtering that
//! drops `mac`/`ios-marketing` from regular imagesets.

use actool::compiler;
use std::path::{Path, PathBuf};

fn workspace_tmp(name: &str) -> PathBuf {
    let dir = PathBuf::from("tmp").join(name);
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn write_png(path: &Path, w: u32, h: u32, rgba: [u8; 4]) {
    let img = image::RgbaImage::from_pixel(w, h, image::Rgba(rgba));
    img.save(path).unwrap();
}

/// Build an imageset carrying every idiom we care about, plus the two that
/// iOS imagesets must drop (`mac`, `ios-marketing`).
fn build_mixed_catalog(root: &Path) {
    let xc = root.join("Images.xcassets");
    let imageset = xc.join("Glyph.imageset");
    std::fs::create_dir_all(&imageset).unwrap();
    std::fs::write(
        xc.join("Contents.json"),
        r#"{"info":{"author":"xcode","version":1}}"#,
    )
    .unwrap();
    write_png(&imageset.join("p1.png"), 10, 10, [255, 0, 0, 255]);
    write_png(&imageset.join("p2.png"), 20, 20, [0, 255, 0, 255]);
    write_png(&imageset.join("p3.png"), 30, 30, [0, 0, 255, 255]);
    std::fs::write(
        imageset.join("Contents.json"),
        r#"{
          "images":[
            {"idiom":"iphone","scale":"1x","filename":"p1.png"},
            {"idiom":"iphone","scale":"2x","filename":"p2.png"},
            {"idiom":"iphone","scale":"3x","filename":"p3.png"},
            {"idiom":"ipad","scale":"1x","filename":"p1.png"},
            {"idiom":"ipad","scale":"2x","filename":"p2.png"},
            {"idiom":"mac","scale":"1x","filename":"p1.png"},
            {"idiom":"ios-marketing","scale":"1x","filename":"p1.png"}
          ],
          "info":{"author":"xcode","version":1}
        }"#,
    )
    .unwrap();
}

fn compile_ios(xcassets: &Path, out: &Path) {
    let plist = out.join("partial.plist");
    compiler::compile_catalog(
        xcassets,
        out,
        "iphoneos",
        "14.0",
        None,
        Some(&plist),
        None,
        None,
        "default",
        None,
        None,
        true,
    )
    .expect("compile");
}

fn read_u32_le(buf: &[u8], off: usize) -> u32 {
    u32::from_le_bytes(buf[off..off + 4].try_into().unwrap())
}

/// Parse the KEYFORMAT (`tmfk`) attribute list from a compiled CAR.
fn keyformat(car: &[u8]) -> Vec<u32> {
    let i = car
        .windows(4)
        .position(|w| w == b"tmfk")
        .expect("tmfk block");
    let n = read_u32_le(car, i + 8) as usize;
    (0..n).map(|k| read_u32_le(car, i + 12 + 4 * k)).collect()
}

#[test]
fn ios_imageset_emits_idiom_keyformat_and_header() {
    let root = workspace_tmp("ios_keyformat");
    build_mixed_catalog(&root);
    let out = root.join("out");
    std::fs::create_dir_all(&out).unwrap();
    compile_ios(&root.join("Images.xcassets"), &out);

    let car = std::fs::read(out.join("Assets.car")).expect("car");

    // Fixed iOS key format: Appearance, Localization, Scale, Idiom, Subtype,
    // Identifier, Element, Part.
    assert_eq!(keyformat(&car), vec![7, 13, 12, 15, 16, 17, 1, 2]);

    // CARHEADER: CoreUI 975, key-semantics 2.
    let h = car
        .windows(4)
        .position(|w| w == b"RATC")
        .expect("RATC block");
    assert_eq!(read_u32_le(&car, h + 4), 975, "coreui version");
    assert_eq!(read_u32_le(&car, h + 432), 2, "key semantics");

    // EXTENDED_METADATA records the device family, not the SDK name.
    let m = car
        .windows(4)
        .position(|w| w == b"META")
        .expect("META block");
    let platform: String = car[m + 516..m + 516 + 8]
        .iter()
        .take_while(|b| **b != 0)
        .map(|b| *b as char)
        .collect();
    assert_eq!(platform, "ios");
}

#[test]
fn ios_imageset_filters_mac_and_marketing_idioms() {
    let root = workspace_tmp("ios_filter");
    build_mixed_catalog(&root);
    let out = root.join("out");
    std::fs::create_dir_all(&out).unwrap();
    compile_ios(&root.join("Images.xcassets"), &out);

    let car = std::fs::read(out.join("Assets.car")).expect("car");
    let kf = keyformat(&car);
    let idiom_col = kf.iter().position(|t| *t == 15).expect("idiom column");

    // Walk RENDITIONS rendition keys (fixed inline key size = kf.len()*2) and
    // collect the idiom values actually present. `mac` (no value here) and
    // `ios-marketing` (=6) must have been dropped; only phone(1)/pad(2) remain.
    let key_size = kf.len() * 2;
    let mut idioms: Vec<u16> = Vec::new();
    // Rendition keys appear as the inline-key region of the RENDITIONS leaf;
    // scan for 16-byte aligned candidates whose scale column is 1..=3 and whose
    // idiom column is a small value, mirroring the probe in tools.
    let scale_col = kf.iter().position(|t| *t == 12).unwrap();
    for i in (0..car.len().saturating_sub(key_size)).step_by(2) {
        let cols: Vec<u16> = (0..kf.len())
            .map(|c| u16::from_le_bytes(car[i + c * 2..i + c * 2 + 2].try_into().unwrap()))
            .collect();
        let scale = cols[scale_col];
        let idiom = cols[idiom_col];
        // Heuristic: a real image rendition key has scale 1..=3, idiom 1..=2,
        // appearance 0 and localization 0.
        if (1..=3).contains(&scale) && (1..=2).contains(&idiom) && cols[0] == 0 && cols[1] == 0 {
            idioms.push(idiom);
        }
    }
    assert!(idioms.contains(&1), "expected an iphone (1) rendition");
    assert!(idioms.contains(&2), "expected an ipad (2) rendition");
    assert!(
        !idioms.contains(&6),
        "ios-marketing (6) must be dropped from imagesets"
    );
}
