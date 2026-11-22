//! Параллельное хеширование файлов (blake3). `partial` — только первый мегабайт.

use rayon::prelude::*;
use std::fs::File;
use std::io::Read;

pub const CHUNK: usize = 1 << 20;

pub fn hash_file(path: &str, full: bool) -> Option<String> {
    let mut f = File::open(path).ok()?;
    let mut h = blake3::Hasher::new();
    let mut buf = vec![0u8; CHUNK];
    loop {
        let n = f.read(&mut buf).ok()?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
        if !full {
            break;
        }
    }
    Some(h.finalize().to_hex().to_string())
}

pub fn hash_many(paths: &[String], full: bool) -> Vec<Option<String>> {
    paths.par_iter().map(|p| hash_file(p, full)).collect()
}
