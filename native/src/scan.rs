//! Параллельный обход папок. Правила те же, что у питоновского `indexer.scan`:
//! пропускаем скрытые и служебные папки, символьные ссылки и junction, применяем исключения.
//! Результат отдаётся пачками через канал: интерфейс видит прогресс сразу, а не после всего обхода.

use crossbeam_channel::{unbounded, Receiver, RecvTimeoutError, Sender};
use globset::{GlobBuilder, GlobMatcher};
use pyo3::prelude::*;
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

/// (путь, имя, размер, mtime, ctime, облачная заглушка)
pub type Entry = (String, String, u64, f64, f64, bool);

const ATTR_REPARSE: u32 = 0x400;
const ATTR_OFFLINE_MASK: u32 = 0x1000 | 0x40000 | 0x400000;

struct Config {
    path_excludes: Vec<String>,
    name_globs: Vec<GlobMatcher>,
    ignored: HashSet<String>,
    noisy: HashSet<String>,
    drive_skip: HashSet<String>,
    nocase: bool,
}

fn norm(s: &str, nocase: bool) -> String {
    let s = if cfg!(windows) { s.replace('/', "\\") } else { s.to_string() };
    let s = s.trim_end_matches(['/', '\\']).to_string();
    if nocase { s.to_lowercase() } else { s }
}

impl Config {
    fn excluded(&self, path: &str, name: &str) -> bool {
        if self.path_excludes.is_empty() && self.name_globs.is_empty() {
            return false;
        }
        let low = name.to_lowercase();
        if self.name_globs.iter().any(|g| g.is_match(&low)) {
            return true;
        }
        if self.path_excludes.is_empty() {
            return false;
        }
        let full = norm(path, self.nocase);
        let sep = std::path::MAIN_SEPARATOR;
        self.path_excludes
            .iter()
            .any(|b| full == *b || (full.starts_with(b.as_str()) && full[b.len()..].starts_with(sep)))
    }
}

fn secs(t: std::io::Result<SystemTime>) -> f64 {
    match t {
        Ok(t) => match t.duration_since(UNIX_EPOCH) {
            Ok(d) => d.as_secs_f64(),
            Err(e) => -e.duration().as_secs_f64(),
        },
        Err(_) => 0.0,
    }
}

#[cfg(windows)]
fn attrs(m: &fs::Metadata) -> u32 {
    use std::os::windows::fs::MetadataExt;
    m.file_attributes()
}
#[cfg(not(windows))]
fn attrs(_m: &fs::Metadata) -> u32 {
    0
}

#[cfg(windows)]
fn ctime(m: &fs::Metadata) -> f64 {
    secs(m.created()) // на Windows st_ctime в Python — время создания
}
#[cfg(unix)]
fn ctime(m: &fs::Metadata) -> f64 {
    use std::os::unix::fs::MetadataExt;
    m.ctime() as f64 + m.ctime_nsec() as f64 / 1e9
}
#[cfg(not(any(windows, unix)))]
fn ctime(m: &fs::Metadata) -> f64 {
    secs(m.created())
}

fn visit<'s>(
    scope: &rayon::Scope<'s>,
    dir: PathBuf,
    at_drive_root: bool,
    cfg: &'s Config,
    tx: &'s Sender<Vec<Entry>>,
    cancel: &'s AtomicBool,
) {
    if cancel.load(Ordering::Relaxed) {
        return;
    }
    let rd = match fs::read_dir(&dir) {
        Ok(r) => r,
        Err(_) => return,
    };
    let mut out: Vec<Entry> = Vec::new();
    for ent in rd {
        let Ok(ent) = ent else { continue };
        let Ok(ft) = ent.file_type() else { continue };
        let name = ent.file_name().to_string_lossy().into_owned();
        let path = ent.path();
        if ft.is_dir() {
            let low = name.to_lowercase();
            if cfg.ignored.contains(&name) || name.starts_with('.') {
                continue;
            }
            if cfg.noisy.contains(&low) || (at_drive_root && cfg.drive_skip.contains(&low)) {
                continue;
            }
            // junction: на Windows это папка с атрибутом reparse point; заходить нельзя, зациклимся
            if cfg!(windows) {
                match ent.metadata() {
                    Ok(m) if attrs(&m) & ATTR_REPARSE == 0 => {}
                    _ => continue,
                }
            }
            let p = path.to_string_lossy();
            if cfg.excluded(&p, &name) {
                continue;
            }
            scope.spawn(move |s| visit(s, path, false, cfg, tx, cancel));
        } else if ft.is_file() {
            let p = path.to_string_lossy().into_owned();
            if cfg.excluded(&p, &name) {
                continue;
            }
            let Ok(m) = ent.metadata() else { continue };
            let cloud = attrs(&m) & ATTR_OFFLINE_MASK != 0;
            out.push((p, name, m.len(), secs(m.modified()), ctime(&m), cloud));
        }
    }
    if !out.is_empty() {
        let _ = tx.send(out);
    }
}

fn is_drive_root(p: &Path) -> bool {
    p.parent().is_none()
}

/// Фоновый обход: создаём, потом забираем пачки через `next_batch`.
#[pyclass]
pub struct Scanner {
    rx: Receiver<Vec<Entry>>,
    cancel: Arc<AtomicBool>,
    carry: std::sync::Mutex<Vec<Entry>>,
}

#[pymethods]
impl Scanner {
    #[new]
    #[pyo3(signature = (root, exclude_paths, exclude_names, ignored_dirs, noisy_dirs, drive_skip, nocase, threads=0))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        root: String,
        exclude_paths: Vec<String>,
        exclude_names: Vec<String>,
        ignored_dirs: Vec<String>,
        noisy_dirs: Vec<String>,
        drive_skip: Vec<String>,
        nocase: bool,
        threads: usize,
    ) -> PyResult<Self> {
        let name_globs = exclude_names
            .iter()
            .filter_map(|p| GlobBuilder::new(&p.to_lowercase()).literal_separator(false).build().ok())
            .map(|g| g.compile_matcher())
            .collect();
        let cfg = Config {
            path_excludes: exclude_paths.iter().map(|p| norm(p, nocase)).collect(),
            name_globs,
            ignored: ignored_dirs.into_iter().collect(),
            noisy: noisy_dirs.into_iter().map(|s| s.to_lowercase()).collect(),
            drive_skip: drive_skip.into_iter().map(|s| s.to_lowercase()).collect(),
            nocase,
        };
        let (tx, rx) = unbounded();
        let cancel = Arc::new(AtomicBool::new(false));
        let c2 = cancel.clone();
        let n = if threads == 0 { std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4).min(16) } else { threads };
        let root_path = PathBuf::from(&root);
        std::thread::spawn(move || {
            let pool = match rayon::ThreadPoolBuilder::new().num_threads(n).build() {
                Ok(p) => p,
                Err(_) => return,
            };
            let at_root = is_drive_root(&root_path);
            pool.scope(|s| visit(s, root_path.clone(), at_root, &cfg, &tx, &c2));
            // tx закрывается здесь: next_batch увидит конец
        });
        Ok(Scanner { rx, cancel, carry: std::sync::Mutex::new(Vec::new()) })
    }

    /// Следующая пачка (до `max_items`), пустой список при таймауте, None когда обход закончен.
    #[pyo3(signature = (max_items=2000, timeout_ms=100))]
    fn next_batch(&self, py: Python<'_>, max_items: usize, timeout_ms: u64) -> Option<Vec<Entry>> {
        py.detach(|| {
            let mut out: Vec<Entry> = std::mem::take(&mut *self.carry.lock().unwrap());
            if out.is_empty() {
                match self.rx.recv_timeout(Duration::from_millis(timeout_ms)) {
                    Ok(v) => out = v,
                    Err(RecvTimeoutError::Timeout) => return Some(out),
                    Err(RecvTimeoutError::Disconnected) => return None,
                }
            }
            while out.len() < max_items {
                match self.rx.try_recv() {
                    Ok(mut v) => out.append(&mut v),
                    Err(_) => break,
                }
            }
            if out.len() > max_items {
                let rest = out.split_off(max_items);
                *self.carry.lock().unwrap() = rest;
            }
            Some(out)
        })
    }

    fn cancel(&self) {
        self.cancel.store(true, Ordering::Relaxed);
    }
}

impl Drop for Scanner {
    fn drop(&mut self) {
        self.cancel.store(true, Ordering::Relaxed);
    }
}
