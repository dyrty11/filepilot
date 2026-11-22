//! Быстрое ядро FilePilot. Подключается из Python как `filepilot._native`.

mod extract;
mod hash;
mod scan;

use pyo3::prelude::*;

#[pyfunction]
#[pyo3(signature = (paths, max_chars, max_zip_member, text_exts))]
fn extract_many(py: Python<'_>, paths: Vec<String>, max_chars: usize, max_zip_member: u64, text_exts: Vec<String>) -> Vec<Option<String>> {
    let lim = extract::Limits { max_chars, max_zip_member, text_exts };
    py.detach(|| extract::extract_many(&paths, &lim))
}

#[pyfunction]
fn decode_bytes(raw: &[u8]) -> String {
    extract::decode_bytes(raw)
}

#[pyfunction]
#[pyo3(signature = (paths, full))]
fn hash_many(py: Python<'_>, paths: Vec<String>, full: bool) -> Vec<Option<String>> {
    py.detach(|| hash::hash_many(&paths, full))
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<scan::Scanner>()?;
    m.add_function(wrap_pyfunction!(extract_many, m)?)?;
    m.add_function(wrap_pyfunction!(decode_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(hash_many, m)?)?;
    m.add("VERSION", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
