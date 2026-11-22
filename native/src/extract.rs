//! Извлечение текста: обычные текстовые файлы и docx/xlsx/pptx/odt/ods/odp (это zip с XML).
//! Логика повторяет `filepilot/extractors.py`. PDF здесь не читаем: его по-прежнему разбирает Python.

use quick_xml::events::Event;
use quick_xml::Reader;
use rayon::prelude::*;
use std::fs::File;
use std::io::Read;
use std::path::Path;

pub struct Limits {
    pub max_chars: usize,
    pub max_zip_member: u64,
    pub text_exts: Vec<String>,
}

fn decode_utf16(raw: &[u8], big: bool) -> String {
    let units: Vec<u16> = raw
        .chunks_exact(2)
        .map(|c| if big { u16::from_be_bytes([c[0], c[1]]) } else { u16::from_le_bytes([c[0], c[1]]) })
        .collect();
    String::from_utf16_lossy(&units)
}

/// BOM -> UTF-8 -> cp1251 -> latin-1, как в Python-версии.
pub fn decode_bytes(raw: &[u8]) -> String {
    if raw.starts_with(&[0xFF, 0xFE]) {
        return decode_utf16(&raw[2..], false);
    }
    if raw.starts_with(&[0xFE, 0xFF]) {
        return decode_utf16(&raw[2..], true);
    }
    let raw = raw.strip_prefix(&[0xEF, 0xBB, 0xBF][..]).unwrap_or(raw);
    if let Ok(s) = std::str::from_utf8(raw) {
        return s.to_string();
    }
    let (s, _, bad) = encoding_rs::WINDOWS_1251.decode(raw);
    if !bad {
        return s.into_owned();
    }
    raw.iter().map(|&b| b as char).collect()
}

fn truncate_chars(s: String, max: usize) -> String {
    match s.char_indices().nth(max) {
        Some((i, _)) => s[..i].to_string(),
        None => s,
    }
}

fn read_text_file(path: &Path, lim: &Limits) -> Option<String> {
    let mut raw = Vec::new();
    File::open(path).ok()?.take((lim.max_chars * 2) as u64).read_to_end(&mut raw).ok()?;
    let head = &raw[..raw.len().min(4096)];
    if head.contains(&0) && !raw.starts_with(&[0xFF, 0xFE]) && !raw.starts_with(&[0xFE, 0xFF]) {
        return Some(String::new()); // бинарный файл с «текстовым» расширением
    }
    Some(truncate_chars(decode_bytes(&raw), lim.max_chars))
}

fn member_wanted(ext: &str, name: &str) -> bool {
    let digits = |s: &str| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit());
    let num_tail = |s: &str| s.bytes().all(|b| b.is_ascii_digit()); // \d* допускает пустую часть
    match ext {
        ".docx" => {
            let Some(rest) = name.strip_prefix("word/").and_then(|r| r.strip_suffix(".xml")) else { return false };
            matches!(rest, "document" | "footnotes" | "endnotes")
                || rest.strip_prefix("header").is_some_and(num_tail)
                || rest.strip_prefix("footer").is_some_and(num_tail)
        }
        ".xlsx" => name == "xl/sharedStrings.xml",
        ".pptx" => {
            name.strip_prefix("ppt/slides/slide").and_then(|r| r.strip_suffix(".xml")).is_some_and(digits)
                || name.strip_prefix("ppt/notesSlides/notesSlide").and_then(|r| r.strip_suffix(".xml")).is_some_and(digits)
        }
        ".odt" | ".ods" | ".odp" => name == "content.xml",
        _ => false,
    }
}

fn is_para(local: &str) -> bool {
    matches!(local, "p" | "si" | "h")
}

/// Абзацы XML: текст всех потомков элементов p/si/h (вложенные абзацы входят и во внешний).
fn xml_paragraphs(data: &[u8]) -> Vec<String> {
    let mut reader = Reader::from_reader(data);
    let mut slots: Vec<String> = Vec::new();
    let mut open: Vec<usize> = Vec::new();
    let mut all = String::new();
    loop {
        match reader.read_event() {
            Ok(Event::Start(e)) => {
                if is_para(e.local_name().as_ref()) {
                    slots.push(String::new());
                    open.push(slots.len() - 1);
                }
            }
            Ok(Event::End(e)) => {
                if is_para(e.local_name().as_ref()) {
                    open.pop();
                }
            }
            Ok(Event::Text(t)) => {
                let s = t.into_inner().into_owned();
                let s = quick_xml::escape::unescape(&s).map(|c| c.into_owned()).unwrap_or(s);
                for &i in &open {
                    slots[i].push_str(&s);
                }
                if !s.trim().is_empty() {
                    if !all.is_empty() {
                        all.push(' ');
                    }
                    all.push_str(s.trim());
                }
            }
            Ok(Event::GeneralRef(r)) => {
                // &amp; &lt; &#1234; и т. п.: quick-xml отдаёт их отдельными событиями
                let s = match r.resolve_char_ref() {
                    Ok(Some(c)) => c.to_string(),
                    _ => match r.as_ref() {
                        "amp" => "&".to_string(),
                        "lt" => "<".to_string(),
                        "gt" => ">".to_string(),
                        "quot" => "\"".to_string(),
                        "apos" => "'".to_string(),
                        _ => String::new(),
                    },
                };
                for &i in &open {
                    slots[i].push_str(&s);
                }
                all.push_str(&s);
            }
            Ok(Event::CData(t)) => {
                let s = t.into_inner().into_owned();
                for &i in &open {
                    slots[i].push_str(&s);
                }
            }
            Ok(Event::Eof) | Err(_) => break,
            _ => {}
        }
    }
    let out: Vec<String> = slots.into_iter().map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect();
    if out.is_empty() && !all.is_empty() {
        vec![all]
    } else {
        out
    }
}

fn read_zip_xml(path: &Path, ext: &str, lim: &Limits) -> Option<String> {
    let mut zip = zip::ZipArchive::new(File::open(path).ok()?).ok()?;
    let mut names: Vec<String> = (0..zip.len())
        .filter_map(|i| zip.by_index_raw(i).ok().and_then(|f| f.name().ok().map(|n| n.into_owned())))
        .filter(|n| member_wanted(ext, n))
        .collect();
    names.sort();
    let mut parts: Vec<String> = Vec::new();
    let mut total = 0usize;
    for name in names {
        let Ok(f) = zip.by_name(&name) else { continue };
        if f.size() > lim.max_zip_member {
            continue;
        }
        let mut data = Vec::new();
        if f.take(lim.max_zip_member).read_to_end(&mut data).is_err() {
            continue;
        }
        for p in xml_paragraphs(&data) {
            total += p.chars().count();
            parts.push(p);
        }
        if total >= lim.max_chars {
            break;
        }
    }
    Some(truncate_chars(parts.join("\n"), lim.max_chars))
}

/// None: тип не поддерживается здесь (например PDF) или файл не прочитался.
pub fn extract(path: &Path, lim: &Limits) -> Option<String> {
    let ext = path.extension().map(|e| format!(".{}", e.to_string_lossy().to_lowercase()))?;
    if lim.text_exts.contains(&ext) {
        return read_text_file(path, lim);
    }
    if matches!(ext.as_str(), ".docx" | ".xlsx" | ".pptx" | ".odt" | ".ods" | ".odp") {
        return std::panic::catch_unwind(|| read_zip_xml(path, &ext, lim)).ok().flatten();
    }
    None
}

pub fn extract_many(paths: &[String], lim: &Limits) -> Vec<Option<String>> {
    paths.par_iter().map(|p| extract(Path::new(p), lim)).collect()
}
