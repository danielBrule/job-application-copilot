from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


def test_streamlit_app_starts_and_creates_private_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_path = Path(__file__).parents[1] / "src" / "job_application_copilot" / "ui" / "app.py"
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JAC_DATA_DIR", str(data_dir))
    monkeypatch.chdir(tmp_path)

    app = AppTest.from_file(str(app_path)).run()

    assert not app.exception
    assert app.title[0].value == "Job Application Copilot"
    assert (data_dir / "database").is_dir()
    assert (data_dir / "cvs").is_dir()
    assert (data_dir / "logs").is_dir()
    assert (data_dir / "reference" / "document_a").is_dir()
    assert (data_dir / "reference" / "document_b").is_dir()
    assert (data_dir / "reference" / "templates").is_dir()
    assert (data_dir / "reference" / "examples").is_dir()
    assert (data_dir / "reference" / "prompts" / "assessment").is_dir()
    assert (data_dir / "reference" / "prompts" / "generation" / "english").is_dir()
    assert (data_dir / "reference" / "prompts" / "generation" / "french").is_dir()
