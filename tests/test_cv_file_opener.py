"""Tests for safe Windows opening of stored CV files."""

from pathlib import Path

import pytest

from job_application_copilot.config import AppSettings
from job_application_copilot.services import CvFileMissingError, CvFileOpener, CvFileOpenError


def test_opens_existing_docx_with_windows_default_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    settings.cv_folder.mkdir(parents=True)
    path = settings.cv_folder / "resume.docx"
    path.write_bytes(b"docx")
    opened: list[Path] = []
    monkeypatch.setattr("os.startfile", lambda value: opened.append(Path(value)))

    CvFileOpener(settings).open(path)

    assert opened == [path.resolve()]


def test_rejects_missing_or_outside_cv_file(tmp_path: Path) -> None:
    settings = AppSettings(_env_file=None, data_dir=tmp_path / "data")
    settings.cv_folder.mkdir(parents=True)

    with pytest.raises(CvFileMissingError, match="missing"):
        CvFileOpener(settings).open(settings.cv_folder / "missing.docx")
    with pytest.raises(CvFileOpenError, match="outside"):
        CvFileOpener(settings).open(tmp_path / "outside.docx")
