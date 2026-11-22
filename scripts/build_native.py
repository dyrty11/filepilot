"""Собирает Rust-ядро и кладёт его рядом с пакетом: filepilot/_native.pyd (Windows) или _native.abi3.so (Linux, macOS).
Нужен установленный Rust (https://rustup.rs). Запуск: python scripts/build_native.py"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CRATE = ROOT / "native"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # консоль Windows бывает не в UTF-8: кириллица не должна ронять сборку
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    subprocess.run(["cargo", "build", "--release", "--manifest-path", str(CRATE / "Cargo.toml")], check=True)
    rel = CRATE / "target" / "release"
    if sys.platform == "win32":
        src, dst = rel / "_native.dll", ROOT / "filepilot" / "_native.pyd"
    elif sys.platform == "darwin":
        src, dst = rel / "lib_native.dylib", ROOT / "filepilot" / "_native.abi3.so"
    else:
        src, dst = rel / "lib_native.so", ROOT / "filepilot" / "_native.abi3.so"
    shutil.copy2(src, dst)
    print(f"Готово: {dst.relative_to(ROOT)} ({dst.stat().st_size // 1024} КБ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
