# ADR-004 — Reference version replacement and remote cleanup

## Status

Accepted

## Decision

- Source documents and templates use DOCX.
- Save every uploaded version locally with a hash and version identifier.
- Activate a new version only after validation and any required OpenAI processing succeed.
- Mark the prior version inactive.
- Do not delete old remote vector stores immediately.
- Provide a manual cleanup action for inactive remote stores.
- Retain local DOCX files and metadata after remote cleanup.

## Rationale

Rare updates do not justify complex version-management or automatic retention policies. Keeping the prior version until the new one works provides a simple rollback path.

## Consequences

- The Settings screen must distinguish active and inactive assets.
- Remote storage can accumulate until manually cleaned.
- A deleted remote store can be recreated from the retained local DOCX if needed.
