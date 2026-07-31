"""Tests for LinkedIn job URL canonicalization."""

import pytest

from job_application_copilot.domain.job_url import canonicalize_linkedin_job_url


@pytest.mark.parametrize(
    ("job_url", "expected"),
    [
        (
            "https://www.linkedin.com/jobs/view/4416123669/",
            "https://www.linkedin.com/jobs/view/4416123669/",
        ),
        (
            "https://www.linkedin.com/jobs/view/4416123669/?trk=job-alert#details",
            "https://www.linkedin.com/jobs/view/4416123669/",
        ),
        (
            "http://linkedin.com/jobs/view/abc123/extra/path?tracking=ignored",
            "https://www.linkedin.com/jobs/view/abc123/",
        ),
    ],
)
def test_canonicalize_linkedin_job_url(job_url: str, expected: str) -> None:
    assert canonicalize_linkedin_job_url(job_url) == expected


@pytest.mark.parametrize(
    "job_url",
    [
        "https://example.com/jobs/view/4416123669/?tracking=kept",
        "https://www.notlinkedin.com/jobs/view/4416123669/",
        "https://www.linkedin.com/jobs/search/?keywords=engineer",
        "https://www.linkedin.com/jobs/view/not-a-valid-id/",
    ],
)
def test_canonicalize_linkedin_job_url_leaves_unrecognized_urls_unchanged(job_url: str) -> None:
    assert canonicalize_linkedin_job_url(job_url) == job_url


def test_canonicalize_linkedin_job_url_preserves_none() -> None:
    assert canonicalize_linkedin_job_url(None) is None
