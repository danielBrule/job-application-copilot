"""Tests for prompt Settings presentation shaping."""

from job_application_copilot.domain import PromptCompleteness
from job_application_copilot.ui.components.prompt_settings import build_completeness_rows


def test_shapes_prompt_completeness_for_settings_table() -> None:
    rows = build_completeness_rows(
        (
            PromptCompleteness(
                pipeline_group="assessment",
                language_code=None,
                required_count=1,
                ready_count=1,
                missing_asset_keys=(),
            ),
            PromptCompleteness(
                pipeline_group="generation/french",
                language_code="fr",
                required_count=2,
                ready_count=1,
                missing_asset_keys=("cv-generation-fr-extension-2",),
            ),
        )
    )

    assert [row.as_dict() for row in rows] == [
        {
            "Pipeline group": "Assessment",
            "Language": "—",
            "Ready": "1/1",
            "Missing": "—",
        },
        {
            "Pipeline group": "Generation / French",
            "Language": "FR",
            "Ready": "1/2",
            "Missing": "cv-generation-fr-extension-2",
        },
    ]
