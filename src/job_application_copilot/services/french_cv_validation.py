"""Deterministic factual-anchor validation for final French CV content."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from job_application_copilot.domain import FinalCvOutput
from job_application_copilot.errors import ApplicationValidationError

_SPACE_PATTERN = re.compile(r"[\s\u00a0\u202f]+")
_NUMBER_PATTERN = re.compile(
    r"(?<![\w])"
    r"(?P<prefix>[£€$])?\s*"
    r"(?P<number>\d+(?:[\s\u00a0\u202f.,]\d+)*)"
    r"\s*(?P<scale>k|m|bn|b|thousand|million|billion|mille|million|milliard)?"
    r"\s*(?P<percent>%|percent|pour\s+cent)?"
    r"\s*(?P<suffix>[£€$])?"
    r"(?![\w])",
    re.IGNORECASE,
)
_LEGAL_NAME_PATTERN = re.compile(
    r"\b(?:[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ&.'’+-]*\s+){1,5}"
    r"(?:Ltd|Limited|plc|Inc|Incorporated|LLC|LLP|Corp|Corporation|GmbH|AG|SA|SAS|SARL|Sàrl|SE)\.?",
)
_MONTHS = {
    "january": 1,
    "janvier": 1,
    "february": 2,
    "fevrier": 2,
    "march": 3,
    "mars": 3,
    "april": 4,
    "avril": 4,
    "may": 5,
    "mai": 5,
    "june": 6,
    "juin": 6,
    "july": 7,
    "juillet": 7,
    "august": 8,
    "aout": 8,
    "september": 9,
    "septembre": 9,
    "october": 10,
    "octobre": 10,
    "november": 11,
    "novembre": 11,
    "december": 12,
    "decembre": 12,
}
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_MONTH_YEAR_PATTERN = re.compile(
    rf"\b(?:(?P<day>\d{{1,2}})\s+)?(?P<month>{_MONTH_PATTERN})\s+(?P<year>\d{{4}})\b",
    re.IGNORECASE,
)
_NUMERIC_DATE_PATTERN = re.compile(
    r"(?<!\d)(?P<day>\d{1,2})[./-](?P<month>\d{1,2})[./-](?P<year>\d{2}|\d{4})(?!\d)"
)
_SCALE_FACTORS = {
    "": Decimal(1),
    "k": Decimal(1_000),
    "thousand": Decimal(1_000),
    "mille": Decimal(1_000),
    "m": Decimal(1_000_000),
    "million": Decimal(1_000_000),
    "b": Decimal(1_000_000_000),
    "bn": Decimal(1_000_000_000),
    "billion": Decimal(1_000_000_000),
    "milliard": Decimal(1_000_000_000),
}
_CURRENCIES = {"£": "GBP", "€": "EUR", "$": "USD"}


class FrenchCvValidationError(ApplicationValidationError):
    """Raised when final French content changes a factual English anchor."""


class FrenchCvValidationService:
    """Compare factual anchors in validated English and French CV structures."""

    def validate(
        self,
        english: FinalCvOutput,
        french: FinalCvOutput,
        *,
        protected_names: Iterable[str] = (),
    ) -> None:
        english_text = _cv_text(english)
        french_text = _cv_text(french)
        mismatches: list[str] = []

        if _date_anchors(english_text) != _date_anchors(french_text):
            mismatches.append("dates")
        if _number_anchors(english_text) != _number_anchors(french_text):
            mismatches.append("numbers or metrics")
        if _name_anchors(english_text, protected_names) != _name_anchors(
            french_text, protected_names
        ):
            mismatches.append("employer or proper names")

        if mismatches:
            labels = ", ".join(mismatches)
            raise FrenchCvValidationError(
                f"French CV factual consistency validation failed for: {labels}."
            )


def _cv_text(output: FinalCvOutput) -> str:
    parts = [output.opening_title.content, output.opening_profile.content]
    for experience in output.experience:
        if experience.title is not None:
            parts.append(experience.title.content)
        if experience.introduction is not None:
            parts.append(experience.introduction)
        parts.extend(experience.bullets)
    for skill in output.skills.entries:
        parts.extend((skill.name, skill.content))
    return "\n".join(parts)


def _date_anchors(text: str) -> Counter[str]:
    anchors: Counter[str] = Counter()
    normalized = _strip_accents(text).lower()
    for match in _MONTH_YEAR_PATTERN.finditer(normalized):
        month = _MONTHS[match.group("month")]
        day = int(match.group("day")) if match.group("day") else 0
        anchors[f"{match.group('year')}-{month:02d}-{day:02d}"] += 1
    for match in _NUMERIC_DATE_PATTERN.finditer(normalized):
        year = int(match.group("year"))
        if year < 100:
            year += 2000
        anchors[f"{year:04d}-{int(match.group('month')):02d}-{int(match.group('day')):02d}"] += 1
    return anchors


def _number_anchors(text: str) -> Counter[str]:
    anchors: Counter[str] = Counter()
    for match in _NUMBER_PATTERN.finditer(text):
        raw_number = match.group("number")
        try:
            number = _decimal_value(raw_number)
        except InvalidOperation:
            continue
        scale = (match.group("scale") or "").lower()
        value = number * _SCALE_FACTORS[scale]
        currency_symbol = match.group("prefix") or match.group("suffix") or ""
        currency = _CURRENCIES.get(currency_symbol, "")
        percent = "percent" if match.group("percent") else ""
        anchors[f"{value.normalize()}|{currency}|{percent}"] += 1
    return anchors


def _decimal_value(raw: str) -> Decimal:
    compact = _SPACE_PATTERN.sub("", raw)
    if "," in compact and "." in compact:
        decimal_separator = "," if compact.rfind(",") > compact.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        compact = compact.replace(thousands_separator, "").replace(decimal_separator, ".")
    elif "," in compact:
        compact = _single_separator_number(compact, ",")
    elif "." in compact:
        compact = _single_separator_number(compact, ".")
    return Decimal(compact)


def _single_separator_number(value: str, separator: str) -> str:
    groups = value.split(separator)
    if len(groups) > 2 or (len(groups) == 2 and len(groups[1]) == 3):
        return "".join(groups)
    return ".".join(groups)


def _name_anchors(text: str, protected_names: Iterable[str]) -> Counter[str]:
    anchors = Counter(
        _normalize_name(match.group()) for match in _LEGAL_NAME_PATTERN.finditer(text)
    )
    folded_text = _normalize_name(text)
    for name in protected_names:
        normalized = _normalize_name(name)
        if normalized:
            anchors[f"protected:{normalized}"] = len(
                re.findall(rf"(?<!\w){re.escape(normalized)}(?!\w)", folded_text)
            )
    return anchors


def _normalize_name(value: str) -> str:
    folded = _strip_accents(value).casefold()
    folded = re.sub(r"[^\w]+", " ", folded)
    return _SPACE_PATTERN.sub(" ", folded).strip()


def _strip_accents(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )
