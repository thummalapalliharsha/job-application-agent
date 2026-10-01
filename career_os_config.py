"""Environment-backed deployment paths with local repository defaults."""
from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

CODE_ROOT = Path(__file__).resolve().parent
STORAGE_ROOT = Path(os.environ.get("CAREER_OS_STORAGE_ROOT", CODE_ROOT)).expanduser().resolve()
DATA_DIR = STORAGE_ROOT / "data"
JOB_DESCRIPTIONS_DIR = STORAGE_ROOT / "job_descriptions"
OUTPUT_DIR = STORAGE_ROOT / "output"
FRONTEND_DIST_DIR = Path(
    os.environ.get("CAREER_OS_FRONTEND_DIR", CODE_ROOT / "frontend" / "dist")
).expanduser().resolve()


def storage_root(root: str | Path | None = None) -> Path:
    if root is None or Path(root).resolve() == CODE_ROOT:
        return STORAGE_ROOT
    return Path(root).expanduser().resolve()


def storage_reference(path: str | Path) -> str:
    resolved = Path(path).resolve()
    for prefix, base in (
        ("data", DATA_DIR),
        ("job_descriptions", JOB_DESCRIPTIONS_DIR),
        ("output", OUTPUT_DIR),
    ):
        try:
            relative = resolved.relative_to(base.resolve())
        except ValueError:
            continue
        return PurePosixPath(prefix, *relative.parts).as_posix()
    try:
        return resolved.relative_to(CODE_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("Path is outside configured application and storage roots") from exc


def resolve_storage_reference(reference: str, root: str | Path | None = None) -> Path | None:
    if not isinstance(reference, str) or not reference.strip():
        return None
    normalized = reference.strip().replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized) or "://" in normalized:
        return None
    parts = PurePosixPath(normalized).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None

    configured_root = storage_root(root)
    if root is not None and Path(root).resolve() != CODE_ROOT:
        bases = {
            "data": configured_root / "data",
            "job_descriptions": configured_root / "job_descriptions",
            "output": configured_root / "output",
        }
    else:
        bases = {
            "data": DATA_DIR,
            "job_descriptions": JOB_DESCRIPTIONS_DIR,
            "output": OUTPUT_DIR,
        }
    base = bases.get(parts[0], CODE_ROOT)
    candidate = base.joinpath(*parts[1:]) if parts[0] in bases else base.joinpath(*parts)
    try:
        candidate.resolve().relative_to(base.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate.resolve()
