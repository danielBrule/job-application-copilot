# Architecture

## 1. Overview

The MVP is a local modular monolith.

```text
Streamlit UI
    ↓
Application services
    ↓
SQLite repositories
    ↓
Local task queue and worker
    ↓
OpenAI client / DOCX renderer / file services
```

## 2. Technology choices

- Python 3.12+
- Streamlit
- SQLite
- SQLAlchemy or SQLModel
- Pydantic
- OpenAI Responses API
- OpenAI Files and vector stores where required
- python-docx
- pytest and Ruff
- Local Windows execution

## 3. Suggested package layout

```text
src/job_application_copilot/
├── ui/
├── domain/
├── services/
├── repositories/
├── llm/
├── tasks/
├── documents/
├── config/
└── observability/
```

Business logic must not live directly in Streamlit pages.

## 4. Background processing

A separate local worker polls a SQLite-backed task table.

- Default concurrency is one.
- Assessment and CV generation may have separate configured worker counts.
- Each concurrent worker uses its own database session.
- A batch is a group of independent tasks.
- A failed task does not stop the batch.
- Running tasks left after a crash become interrupted and retryable.

No Redis, Celery, cloud queue or microservice is required.

## 5. Document handling

### Document A

The complete active Document A is supplied to every assessment call. It is not split or semantically filtered for the MVP.

### Document B

Document B is maintained as one DOCX. The application extracts headings locally and routes mandatory sections deterministically based on the selected CV lane.

Optional semantic retrieval may add relevant passages. It must never replace the fixed rules or lane sections.

### French references

Previous French CVs are style references only. They cannot establish factual evidence.

### Templates

English and French templates remain local DOCX files. The model returns structured content, and python-docx populates a copy of the template.

## 6. Reference versioning

A new version is active only after local validation and any required remote processing succeed.

The old local DOCX and metadata remain inactive. Old remote stores are retained until the user chooses manual cleanup.

## 7. OpenAI calls

- Use the Responses API.
- Use structured outputs for assessment and final CV data.
- Validate every response locally with Pydantic.
- Persist intermediate prompt-stage output.
- Record model, response ID, tokens, duration and reference versions.
- Do not depend on hidden chat state.

Official references:

- https://platform.openai.com/docs/quickstart
- https://platform.openai.com/docs/api-reference/files
- https://platform.openai.com/docs/api-reference/vector-stores-files
- https://platform.openai.com/docs/guides/structured-outputs

## 8. Local files

Recommended private structure:

```text
data/
├── database/
├── reference/
├── cvs/
└── logs/
```

Generated and uploaded CVs share one folder. All generated CVs use one naming convention.
Versioned prompts are private local assets stored below `data/reference/prompts`, separated
into assessment, English-generation and French-generation directories.

## 9. Security and privacy

- Secrets only through environment variables.
- Private inputs and outputs excluded from Git.
- General logs should store IDs and errors, not full CV/JD content by default.
- External model calls are explicit.
- No automatic employer interaction.

## 10. Simplicity constraints

Do not introduce:

- microservices;
- browser automation;
- automatic submission;
- multi-user authentication;
- a browser-based Word editor;
- a cloud database;
- complex event infrastructure;
- Word-document version history.
