# Architecture

## 1. Overview

The MVP is a local modular monolith.

```text
Streamlit entry points and components
    |
    v
Application services
    |---------------|------------------|
    v               v                  v
SQLAlchemy       Private local      OpenAI adapter
repositories     files / DOCX       (explicit workflows)
    |
    v
SQLite / Alembic
```

The local task queue, worker, retained attempts, recovery and configurable concurrency are
implemented execution foundations for assessment and CV generation. Settings reference-asset
flows remain synchronous after an explicit user action. Document B processing emits
presentation-neutral progress events so Settings can report its current phase and indexed-section
count without moving reference-asset activation into the background queue.

## 2. Technology choices

- Python 3.12+
- Streamlit
- SQLite
- SQLAlchemy 2.x and Alembic
- Pydantic
- OpenAI Responses API
- OpenAI Files and vector stores where required
- python-docx
- pytest, Ruff and mypy
- Local Windows execution

## 3. Package responsibilities

| Package or module | Responsibility | Must not own |
| --- | --- | --- |
| `ui/app.py`, `ui/pages` | Startup, Streamlit navigation and thin page composition | Transactions or business rules |
| `ui/components` | Widget state, presentation and safe user-facing errors | Direct database or OpenAI access |
| `services` | Use-case orchestration, transaction boundaries and compensation | Streamlit rendering |
| `repositories` | SQLAlchemy queries and persistence operations | Workflow policy or remote calls |
| `domain` | Validated application values, enums and presentation-neutral read models | Filesystem, database or network side effects |
| `llm` | Capability protocols and the production OpenAI adapter | Reference-asset activation policy |
| `documents` | DOCX validation and deterministic Document B extraction | Persistence or UI behavior |
| `config` | Typed environment and `.env` settings | Filesystem creation while merely loading settings |
| `observability` | Private structured logging and secret redaction | User-visible error translation |
| `errors.py` | Stable semantic categories for expected boundary failures | Workflow-specific error messages |

Public workflow exception names remain specific to their service. Their semantic base classes
allow callers to distinguish invalid input, missing data, storage, integrity and external-service
failures without catching broad built-in exceptions. Existing `ValueError`, `LookupError` and
`RuntimeError` compatibility is retained.

### Package layout

```text
src/job_application_copilot/
├── ui/
│   ├── pages/
│   └── components/
├── domain/
├── services/
├── repositories/
├── llm/
├── documents/
├── config/
└── observability/
```

Business logic must not live directly in Streamlit pages.

Model-produced assessment relevance and the optional human relevance override remain separate.
The current assessment owns the model value; the job owns the nullable override. Presentation
uses the override when present and otherwise falls back to the model value.

Assessment role families and CV lanes are one configured taxonomy. Lane identifiers are validated
strings, and membership is checked against the current validated routing set bound to the active
Document B version. No global Python enum defines a person's lane catalogue.

`ui/pages` contains only the thin entry points registered with Streamlit navigation. They
load dependencies and compose a page. Forms, tables, filters and rendered page sections live
under `ui/components`; these components call application services and contain presentation
logic, not business rules. Application startup and process-local dependency construction remain
at `ui/app.py` and `ui/dependencies.py`.

## 4. Background processing

Background processing uses a separate local worker polling a SQLite-backed task table.

Before CV-generation stage one, the worker verifies that the current assessment used the active
READY assessment prompt and Document A versions. It reassesses mismatches in the claimed task and
stops that task when reassessment fails; the prior successful assessment remains retained.

- Default concurrency is one.
- Assessment and CV generation may have separate configured worker counts.
- Each concurrent worker uses its own database session.
- A batch is a group of independent tasks.
- A failed task does not stop the batch.
- Running tasks left after a crash become interrupted and retryable.
- A logical task retains one execution-attempt row per worker claim. Manual retry returns only
  that task to `PENDING`; the next claim creates a new attempt and completed sibling tasks remain
  unchanged.
- Background Runs polls displayed active work once per minute and also provides explicit refresh.
  UI refresh reads durable state only and does not signal or control the worker.

No Redis, Celery, cloud queue or microservice is required.

## 5. Document handling

### Document A

The complete active Document A is supplied to every assessment call. It is not split or semantically filtered for the MVP.
Input preparation resolves only the canonical active `READY` Document A and requires its
persisted OpenAI file ID. It returns a complete Responses API file reference together with the
reference-asset ID, version, hash, stored filename and upload timestamp for traceability.
There is no local-text fallback: a missing active version or file ID stops assessment with an
actionable error so the document can be activated again.

### Document B

Document B is maintained as one DOCX. The application extracts headings locally and routes mandatory
section trees deterministically from the user-confirmed selected CV lane. A versioned SQLite routing
set is bound to one exact Document B version and maps each lane to mandatory and optional section
IDs, inclusion roles, descendant handling, exclusions and output-template requirements.

Optional semantic retrieval may add relevant CV material only from section-derived records
authorised by that routing set. It must never replace the fixed rules or lane sections, determine
the primary lane, or establish factual evidence.

Evidence-supported material mandate dimensions may add configured thematic bullet-library sections
through controlled support-category tags retained in the assessment. The resolved primary lane
remains the sole source of summary, experience framing and positioning-playbook material.

Section-aware retrieval receives an already resolved routing packet; it does not select a lane.
It queries only `VECTOR_SCOPE_REQUIRED` and `VECTOR_SCOPE_OPTIONAL` section IDs, applies the
Document B version and section-ID filter at the vector-store boundary, then verifies the returned
metadata against locally registered section-derived source records. Results without matching
version, section ID and source record are discarded. Retrieval traces are private local data and
record the query, routing-set version and returned deterministic passage IDs; they are not written
to application logs. Vector-store failure leaves the direct routing packet available.

Local extraction preserves the document preamble, Word heading levels, ordered paragraph and
table text, and uses a conservative bold-numbered fallback when a Word heading style is absent.
Each non-overlapping section has a deterministic ID derived from its heading number or
hierarchical title path and is stored against the exact Document B reference-asset version.
Document B cannot be activated unless this local extraction succeeds. Versions activated before
the section schema existed are extracted on their first section read. A section-tree query
returns a selected heading followed by its ordered descendants until the next peer or ancestor,
allowing deterministic routing to consume complete blocks without duplicating stored text.

Document B vector stores contain only section-derived text sources, never the complete DOCX.
Each source carries the exact Document B version and local section ID as metadata, and every
retrieval applies the authorised section-ID filter. This is necessary to enforce scoped retrieval;
a whole-document search cannot prove that a returned chunk belongs to an authorised local section.

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
DOCX validation, so they become `READY` and active immediately. Documents A and B require OpenAI
processing: local storage first creates an inactive `PENDING` candidate, and the combined Settings
workflow activates it only after its remote processing succeeds. The candidate never displaces the
current active document on failure.

Prompt and DOCX storage share small immutable-file primitives for path containment, SHA-256
calculation, exclusive creation and compensating deletion. The asset services retain ownership
of validation, version naming, activation and repository rules. Compensation removes only a file
created by the current operation; an existing destination is never overwritten or deleted.

French reference-example identity is derived deterministically from its normalized user-facing
name; the internal asset key is not user input. Content hashes are unique across the whole
reference-example category so the same CV cannot be added under another name. Removal is a
reversible active-state change: retained READY versions and local files remain available for
restoration and do not count toward configured readiness while inactive.

Only canonical Document A and Document B versions are authorised for OpenAI file upload. The
service verifies the retained local file against its recorded hash and uploads the exact bytes
with the Files API `user_data` purpose. A successful Document A upload is sufficient to make that
version `READY` and active. Settings performs Document A storage, upload and activation through
one explicit upload-or-replace-and-activate action. A successful Document B upload stores its file ID but leaves the
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

Document A processing, Document B processing, cleanup and restoration share one remote-operation
lifecycle. It acquires the non-blocking process guard, creates at most one workflow-owned client,
translates configuration failures into the workflow's existing safe exception and releases the
client and guard on every exit path. Domain, persistence, integrity and compensation failures are
not absorbed by this lifecycle boundary. Client close failures propagate after the guard has
been released.

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

## 7. External integration boundaries

Services depend on capability-specific protocols rather than the concrete OpenAI client:
file operations, vector-store operations, cleanup operations and a closable composite reference
client. `OpenAIClient` remains the single production implementation. This keeps file upload,
indexing and cleanup contracts independently testable without changing the public adapter.

Remote reference operations have user-visible local side effects before they contact OpenAI:
candidate versions and processing states are persisted so recovery can resume from recorded file
or vector-store identifiers. A retry reuses each successfully persisted identifier. It does not
repeat a completed remote create or deletion step. The unavoidable create-before-ID-persistence
crash window is documented in the reference-versioning section above.

### OpenAI calls

- Use the Responses API.
- Use structured outputs for assessment and final CV data.
- Validate every response locally with Pydantic.
- Persist intermediate prompt-stage output.
- Record model, response ID, tokens, duration and reference versions.
- Do not depend on hidden chat state.

Assessment context composition remains provider-neutral and inspectable before execution. It emits
the stable prompt/schema/complete-Document-A prefix before variable job metadata and the full job
description, together with version traceability and a privacy-safe cache identity. The OpenAI
adapter owns conversion of that validated context into the final Responses API request.

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

Each installation also owns
`data/reference/routing/document-b-lane-routes.yaml`. It is created from the committed
[`templates/document-b-lane-routes.template.yaml`](../templates/document-b-lane-routes.template.yaml)
and customised for that installation's Document B. The editable YAML remains private; only a
validated routing set bound to an exact Document B version is used at runtime.

Prompt definitions are stored separately from their immutable text versions. A definition
declares the stable asset key, enum-free pipeline group, optional language, position and enabled
state; `reference_assets` records each UTF-8 text version, hash and active state. This allows
missing required prompts and completeness to be reported even when no prompt file exists.
Adding another prompt group or language requires data changes only. Prompt execution remains a
later pipeline responsibility.

The repository contains one generic, non-private assessment prompt template. Startup copies it
through the normal prompt service into private storage as active version 1 only when no retained
assessment prompt version exists. The operation is idempotent and never overwrites or reactivates
an installation's prompt history.

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
