"""Cross-language factual-anchor validation for final French CV output."""

import pytest

from job_application_copilot.domain import FinalCvOutput
from job_application_copilot.services import (
    FrenchCvValidationError,
    FrenchCvValidationService,
)


def cv_output(*, profile: str, introduction: str, bullet: str) -> FinalCvOutput:
    return FinalCvOutput.model_validate(
        {
            "opening_title": {
                "placeholder": "[OPENING_TITLE]",
                "content": "AI Solutions Director",
            },
            "opening_profile": {
                "placeholder": "[OPENING_PROFILE]",
                "content": profile,
            },
            "experience": [
                {
                    "placeholder": "[EXPERIENCE_CURRENT]",
                    "title": None,
                    "introduction": introduction,
                    "bullets": [bullet],
                }
            ],
            "skills": {
                "placeholder": "[SKILLS]",
                "entries": [{"name": "Architecture", "content": "Evidence-led delivery"}],
            },
        }
    )


def english_output() -> FinalCvOutput:
    return cv_output(
        profile="Improved delivery by 42% between January 2020 and February 2022.",
        introduction="Director at Example Ltd. supporting Google.",
        bullet="Delivered £2.5m in validated outcomes with shared ownership.",
    )


def french_output() -> FinalCvOutput:
    return cv_output(
        profile="Amélioration de la livraison de 42 % entre janvier 2020 et février 2022.",
        introduction="Directeur chez Example Ltd. au service de Google.",
        bullet="Livraison de 2,5 M£ de résultats validés sous responsabilité partagée.",
    )


def test_accepts_french_formatting_that_preserves_factual_anchors() -> None:
    FrenchCvValidationService().validate(
        english_output(), french_output(), protected_names=("Google",)
    )


def test_rejects_changed_metric() -> None:
    french = french_output().model_copy(
        update={
            "opening_profile": french_output().opening_profile.model_copy(
                update={
                    "content": (
                        "Amélioration de la livraison de 47 % entre janvier 2020 et février 2022."
                    )
                }
            )
        }
    )

    with pytest.raises(FrenchCvValidationError, match="numbers or metrics"):
        FrenchCvValidationService().validate(english_output(), french)


def test_rejects_changed_month_with_same_year() -> None:
    french = french_output().model_copy(
        update={
            "opening_profile": french_output().opening_profile.model_copy(
                update={
                    "content": (
                        "Amélioration de la livraison de 42 % entre mars 2020 et février 2022."
                    )
                }
            )
        }
    )

    with pytest.raises(FrenchCvValidationError, match="dates"):
        FrenchCvValidationService().validate(english_output(), french)


def test_rejects_changed_legal_employer_name() -> None:
    french = french_output().model_copy(
        update={
            "experience": (
                french_output()
                .experience[0]
                .model_copy(
                    update={"introduction": "Directeur chez Exemple SAS au service de Google."}
                ),
            )
        }
    )

    with pytest.raises(FrenchCvValidationError, match="employer or proper names"):
        FrenchCvValidationService().validate(english_output(), french)


def test_rejects_changed_protected_employer_without_legal_suffix() -> None:
    french = french_output().model_copy(
        update={
            "experience": (
                french_output()
                .experience[0]
                .model_copy(
                    update={"introduction": "Directeur chez Example Ltd. au service de Alphabet."}
                ),
            )
        }
    )

    with pytest.raises(FrenchCvValidationError, match="employer or proper names"):
        FrenchCvValidationService().validate(english_output(), french, protected_names=("Google",))
