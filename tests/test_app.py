from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_app_starts() -> None:
    app_path = Path(__file__).parents[1] / "src" / "job_application_copilot" / "ui" / "app.py"

    app = AppTest.from_file(str(app_path)).run()

    assert not app.exception
    assert app.title[0].value == "Job Application Copilot"
