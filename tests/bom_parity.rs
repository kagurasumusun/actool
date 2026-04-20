//! Byte-for-byte parity with the Python BOMWriter for a fixed input.
//! Regenerate `tmp/bom_python_reference.bin` with the equivalent Python
//! script if the writer changes.

use actool::bom::BomWriter;

#[test]
fn matches_python_reference() {
    let mut bom = BomWriter::new();
    bom.add_named_block("CARHEADER", b"hello world data".to_vec());
    let entries = vec![
        (b"key1".to_vec(), b"valA".to_vec()),
        (b"key2".to_vec(), b"valB".to_vec()),
    ];
    bom.add_tree("TESTTREE", &entries, 4096);
    let raw: Vec<(u32, Vec<u8>)> =
        vec![(1, b"aaaa".to_vec()), (2, b"bbbb".to_vec())];
    bom.add_raw_key_tree("RTBL", &raw, 1024);
    let ours = bom.to_bytes();

    let reference_path = "tests/parity_references/bom_python_reference.bin";
    if !std::path::Path::new(reference_path).exists() {
        eprintln!("Skipping: {reference_path} not present");
        return;
    }
    let reference = std::fs::read(reference_path).expect("read reference");
    if ours != reference {
        // Dump ours for debugging
        let _ = std::fs::write("tmp/bom_rust_output.bin", &ours);
        let mut diffs = 0;
        for (i, (a, b)) in ours.iter().zip(reference.iter()).enumerate() {
            if a != b && diffs < 20 {
                eprintln!("@{i:#06x}: rust={a:02x} python={b:02x}");
                diffs += 1;
            }
        }
        panic!(
            "BOM byte mismatch: rust_len={} python_len={}",
            ours.len(),
            reference.len()
        );
    }
}
