"""Small filesystem primitives for immutable private application assets."""

from __future__ import annotations

import hashlib
from pathlib import Path


class ImmutableFilePathError(ValueError):
    """Raised when an immutable asset path escapes its configured root."""


class ImmutableFileExistsError(FileExistsError):
    """Raised when an immutable destination already exists."""


class ImmutableFileWriteError(OSError):
    """Raised when an immutable destination cannot be written completely."""


def sha256_file_hash(content: bytes) -> str:
    """Return the canonical persisted SHA-256 value for exact file bytes."""

    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def resolve_path_within(root: Path, path: Path) -> Path:
    """Resolve a path and require it to remain at or below the configured root."""

    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ImmutableFilePathError(f"Path is outside the configured root: {path}")
    return resolved_path


def relative_path_within(root: Path, path: Path) -> str:
    """Return a portable relative path after enforcing root containment."""

    resolved_root = root.resolve()
    resolved_path = resolve_path_within(resolved_root, path)
    return resolved_path.relative_to(resolved_root).as_posix()


def write_bytes_exclusively(path: Path, content: bytes) -> None:
    """Create one new file without overwrite and remove a partially written file."""

    created = False
    try:
        with path.open("xb") as target:
            created = True
            target.write(content)
    except FileExistsError as error:
        raise ImmutableFileExistsError(path) from error
    except OSError as error:
        remove_created_file(path, created=created)
        raise ImmutableFileWriteError(path) from error


def remove_created_file(path: Path | None, *, created: bool) -> None:
    """Compensate a failed transaction only when this operation created the file."""

    if path is not None and created:
        path.unlink(missing_ok=True)
