"""Validation tests for template-parameterised final CV content."""

import pytest
from pydantic import ValidationError

from job_application_copilot.domain import FinalCvOutput


def payload() -> dict[str, object]:
    return {
        "opening_title": {
            "placeholder": "[OPENING_TITLE]",
            "content": "AI & Data Solution Architecture Leader",
        },
        "opening_profile": {
            "placeholder": "[OPENING_PROFILE]",
            "content": "Evidence-led data and AI architecture leader.",
        },
        "experience": [
            {
                "placeholder": "[EXPERIENCE_INDEPENDENT_GENAI]",
                "bullets": ["Designed retrieval approaches for independent research."],
            },
            {
                "placeholder": "[EXPERIENCE_EKIMETRICS]",
                "title": {
                    "placeholder": "[EKIMETRICS_TITLE]",
                    "content": "Head of Data / Technical Lead",
                },
                "introduction": "Led delivery across data and technology teams.",
                "bullets": ["Built durable delivery standards."],
            },
        ],
        "skills": {
            "placeholder": "[SKILLS]",
            "entries": [
                {
                    "name": "Solution architecture",
                    "content": "System and data architecture, APIs and integration patterns.",
                }
            ],
        },
    }


def test_parses_representative_template_content_without_losing_order() -> None:
    output = FinalCvOutput.model_validate(payload())

    assert output.experience[1].title is not None
    assert output.experience[1].title.placeholder == "[EKIMETRICS_TITLE]"
    assert output.skills.entries[0].name == "Solution architecture"


@pytest.mark.parametrize(
    "title",
    ("Senior Manager", "Senior Manager | Data & AI Value Creation"),
)
def test_allows_a_resolved_factual_experience_title_with_optional_positioning_suffix(
    title: str,
) -> None:
    values = payload()
    values["experience"][1]["title"]["content"] = title  # type: ignore[index]

    output = FinalCvOutput.model_validate(values)

    assert output.experience[1].title is not None
    assert output.experience[1].title.content == title


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("opening_title", "placeholder"), "OPENING_TITLE"),
        (("opening_profile", "content"), " "),
        (("experience", 0, "bullets"), []),
        (("skills", "entries", 0, "content"), ""),
    ],
)
def test_rejects_invalid_required_generated_content(
    path: tuple[str | int, ...], value: object
) -> None:
    values = payload()
    target: object = values
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(ValidationError):
        FinalCvOutput.model_validate(values)


def test_rejects_duplicate_generated_placeholders() -> None:
    values = payload()
    values["skills"]["placeholder"] = "[OPENING_TITLE]"  # type: ignore[index]

    with pytest.raises(ValidationError, match="unique DOCX placeholder"):
        FinalCvOutput.model_validate(values)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("experience", 1, "title", "content"), "[Factual job title]"),
        (("opening_profile", "content"), "[Actual job title]"),
        (("experience", 0, "introduction"), "[Job title]"),
        (("skills", "entries", 0, "content"), "[Company]"),
        (("skills", "entries", 0, "name"), "[Location]"),
        (
            ("experience", 0, "bullets"),
            ["[Dates]"],
        ),
    ],
)
def test_rejects_known_unresolved_template_placeholders_in_user_visible_cv_content(
    path: tuple[str | int, ...], value: object
) -> None:
    values = payload()
    target: object = values
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(ValidationError, match="unresolved template placeholder"):
        FinalCvOutput.model_validate(values)


def test_allows_legitimate_brackets_in_cv_prose() -> None:
    values = payload()
    values["opening_profile"]["content"] = "Led [Python, SQL] delivery standards."  # type: ignore[index]

    output = FinalCvOutput.model_validate(values)

    assert output.opening_profile.content == "Led [Python, SQL] delivery standards."


def test_allows_placeholder_words_when_they_are_not_bracketed() -> None:
    values = payload()
    values["opening_profile"]["content"] = (  # type: ignore[index]
        "Led company delivery across multiple locations and reporting dates."
    )

    output = FinalCvOutput.model_validate(values)

    assert "company delivery" in output.opening_profile.content


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("experience", 0, "bullets"), ["]},{"]),
        (("experience", 0, "introduction"), "]}, {"),
        (("opening_profile", "content"), "[ ]"),
        (("skills", "entries", 0, "content"), "Evidence ]}, { artifact"),
    ],
)
def test_rejects_structured_output_serialization_fragments_in_cv_prose(
    path: tuple[str | int, ...], value: object
) -> None:
    values = payload()
    target: object = values
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(ValidationError, match="serialization fragment"):
        FinalCvOutput.model_validate(values)


def test_allows_a_different_user_template_slot_name() -> None:
    values = payload()
    values["experience"][0]["placeholder"] = "[EXPERIENCE_CURRENT_ROLE]"  # type: ignore[index]

    output = FinalCvOutput.model_validate(values)

    assert output.experience[0].placeholder == "[EXPERIENCE_CURRENT_ROLE]"
