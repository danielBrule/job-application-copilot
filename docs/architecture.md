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
│   ├── pages/
│   └── components/
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

`ui/pages` contains only the thin entry points registered with Streamlit navigation. They
load dependencies and compose a page. Forms, tables, filters and rendered page sections live
under `ui/components`; these components call application services and contain presentation
logic, not business rules. Application startup and process-local dependency construction remain
at `ui/app.py` and `ui/dependencies.py`.

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

Local replacement is one logical operation across immutable file creation and database metadata.
If metadata storage or activation fails, the new file is removed and the database transaction
restores the previous active version. Templates and French reference examples require only local
DOCX validation, so they become `READY` and active immediately. Documents A and B require later
OpenAI processing: local replacement stores them as inactive `PENDING` candidates and does not
displace the current active document.

French reference-example identity is derived deterministically from its normalized user-facing
name; the internal asset key is not user input. Content hashes are unique across the whole
reference-example category so the same CV cannot be added under another name. Removal is a
reversible active-state change: retained READY versions and local files remain available for
restoration and do not count toward configured readiness while inactive.

Only canonical Document A and Document B versions are authorised for OpenAI file upload. The
service verifies the retained local file against its recorded hash and uploads the exact bytes
with the Files API `user_data` purpose. A successful Document A upload is sufficient to make that
version `READY` and active. A successful Document B upload stores its file ID but leaves the
version inactive and `PENDING` for vector-store processing. Upload failures preserve the prior
active version and store one sanitised, retryable processing error.

Each uploaded Document B version receives one vector store. The application persists the store
ID, polls the attached file with a bounded wait, and runs one direct validation search. Only a
`completed` file with retrievable content can make the candidate `READY` and active. Deactivating
the prior version and activating the candidate occur in one database transaction, so failure
restores the prior active version. Failed and inactive stores retain their IDs and processed
usage bytes for the explicit cleanup workflow; indexing itself has no reported model-token usage.
The Settings page stores a new Document B version and runs this lifecycle synchronously through
one explicit upload-or-replace-and-activate action. A separate processing action remains for
pending, failed or interrupted candidates. One workflow-owned OpenAI client is closed after
success or failure, and an existing file or vector-store ID makes retries resume without
recreating that resource. A locally `PROCESSING` version without the next remote ID is also
retryable after an application restart.
One process-local guard rejects a second attempt while the current application process is still
working and also prevents cleanup from racing with activation, without blocking recovery after
that process restarts.

Explicit cleanup lists tracked remote identifiers on inactive, non-processing reference
versions. It deletes a vector store before its underlying OpenAI file and persists each cleared
association separately, while retaining the local DOCX and historical metadata. Document A
therefore cleans only its uploaded file; Document B cleans its vector store and uploaded file.
An explicit restore action can rebuild those resources for an inactive retained Document A or
Document B version. It reuses the existing local version, verifies its recorded hash, and follows
the normal upload and Document B indexing paths. Activation remains atomic, so the current active
version is not displaced by a failed restoration.
Because a process can stop between a successful remote create and local ID persistence,
untracked-resource discovery remains a separate concern: resource names alone are not a safe
ownership boundary when multiple local checkouts share an OpenAI project.

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

Prompt definitions are stored separately from their immutable text versions. A definition
declares the stable asset key, enum-free pipeline group, optional language, position and enabled
state; `reference_assets` records each UTF-8 text version, hash and active state. This allows
missing required prompts and completeness to be reported even when no prompt file exists.
Adding another prompt group or language requires data changes only. Prompt execution remains a
later pipeline responsibility.

The Settings asset overview is a read-only aggregation over the reference-asset repository
and prompt-definition service. Stable non-prompt pipeline roles use canonical asset keys,
while prompt groups and French reference examples remain data-driven. It reports active
versions separately from the latest inactive candidate, allowing an active ready asset to
remain usable while a newer version is pending or failed. The Streamlit layer only shapes
this presentation-neutral read model into table rows.

## 9. Security and privacy

- Secrets only through environment variables.
- Private inputs and outputs excluded from Git.
- Logs are private local data and may contain application content required for diagnostics.
- API keys, authentication tokens, passwords and other secrets must never be logged.
- UI and worker processes use separate rotating files with one shared format and correlation IDs.
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
