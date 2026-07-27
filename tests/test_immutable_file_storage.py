"""Tests for shared immutable private-file primitives."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_application_copilot.services.immutable_file_storage import (
    ImmutableFileExistsError,
    ImmutableFilePathError,
    ImmutableFileWriteError,
    relative_path_within,
    remove_created_file,
    resolve_path_within,
    sha256_file_hash,
    write_bytes_exclusively,
)


def test_hash_uses_canonical_persisted_format() -> None:
    assert sha256_file_hash(b"content") == (
        "sha256:ed7002b439e9ac845f22357d822bac1444730fbdb6016d3ec9432297b9ec9f73"
    )


def test_resolves_and_relativizes_only_paths_within_root(tmp_path: Path) -> None:
    root = tmp_path / "reference"
    nested = root / "prompts" / "assessment.txt"

    assert resolve_path_within(root, nested) == nested.resolve()
    assert relative_path_within(root, nested) == "prompts/assessment.txt"

    with pytest.raises(ImmutableFilePathError, match="outside"):
        resolve_path_within(root, tmp_path / "outside.txt")


def test_exclusive_write_preserves_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "asset.txt"
    path.write_bytes(b"existing")

    with pytest.raises(ImmutableFileExistsError):
        write_bytes_exclusively(path, b"replacement")

    assert path.read_bytes() == b"existing"


def test_exclusive_write_removes_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "asset.txt"

    class FailingTarget:
        def __enter__(self) -> FailingTarget:
            path.touch()
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def write(self, content: bytes) -> None:
            del content
            raise OSError("disk full")

    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: FailingTarget())

    with pytest.raises(ImmutableFileWriteError) as captured:
        write_bytes_exclusively(path, b"content")

    assert str(captured.value.__cause__) == "disk full"
    assert not path.exists()


def test_compensation_removes_only_files_created_by_current_operation(tmp_path: Path) -> None:
    path = tmp_path / "asset.txt"
    path.write_bytes(b"existing")

    remove_created_file(path, created=False)
    assert path.exists()

    remove_created_file(path, created=True)
    assert not path.exists()
