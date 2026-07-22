# ADR-003 — DOCX generation and editing

## Status

Accepted

## Decision

- Generate structured CV content first.
- Populate a copy of a fixed English or French DOCX template with python-docx.
- Store all generated CVs in one folder.
- Use the filename `resume - Daniel Brule - YYYY-MM-DD - Company.docx`.
- Open the file in the Windows default DOCX application for editing.
- Require an explicit approval click in the application.
- Do not maintain Word-document version history.

## Rationale

Microsoft Word already provides the required document-editing experience. Building an in-browser Word-like editor would add substantial complexity with little benefit.

## Consequences

- Template placeholder mapping must be deterministic.
- The application cannot verify the nature of edits made in Word.
- Regeneration replaces the active generated CV only after successful completion.
