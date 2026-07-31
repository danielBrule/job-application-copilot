"""Canonical job URL helpers."""

import re
from urllib.parse import urlsplit

LINKEDIN_JOB_ID_PATTERN = re.compile(r"[A-Za-z0-9]+")
LINKEDIN_JOB_HOSTS = frozenset({"linkedin.com", "www.linkedin.com"})


def canonicalize_linkedin_job_url(job_url: str | None) -> str | None:
    """Return the stable LinkedIn job URL when the URL has a recognizable job ID.

    Other job sites and malformed LinkedIn job URLs remain unchanged so this
    narrow normalizer cannot alter unrelated duplicate-detection behavior.
    """

    if job_url is None:
        return None

    parsed = urlsplit(job_url)
    hostname = parsed.hostname.lower() if parsed.hostname is not None else None
    path_parts = parsed.path.split("/")
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or hostname not in LINKEDIN_JOB_HOSTS
        or len(path_parts) < 4
        or path_parts[1].lower() != "jobs"
        or path_parts[2].lower() != "view"
        or LINKEDIN_JOB_ID_PATTERN.fullmatch(path_parts[3]) is None
    ):
        return job_url

    return f"https://www.linkedin.com/jobs/view/{path_parts[3]}/"
