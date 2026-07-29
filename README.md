# Job Application Copilot

[![CI](https://github.com/danielBrule/job-application-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/danielBrule/job-application-copilot/actions/workflows/ci.yml)

An **evidence-grounded career decision and document-generation workflow** for assessing opportunities, selecting applications deliberately, and producing traceable, reviewable CVs.

The project is intentionally **not an automated mass-application tool**. It does not submit applications, automate employer portals, or remove human approval from career decisions.

## What it does

The workflow uses two controlled career documents:

- **Document A** assesses the job and determines fit, role family, positioning and whether to
  pursue it.
- **Document B** contains approved CV content, evidence, the bullet library and rules used to
  generate a tailored CV.

1. Stores job descriptions and basic job information locally.
2. Assesses selected jobs using Document A.
3. Displays structured assessments for human review.
4. Lets the user select jobs for CV generation or upload an existing CV.
5. Generates English or French DOCX CVs using Document B, configured prompts and fixed templates.
6. Opens the DOCX directly in Microsoft Word for manual editing.
7. Records explicit CV approval.
8. Tracks application status, contacts, interviews, notes and next actions.
9. Reports simple workflow, token and processing-time KPIs.

### How Documents A and B work

- **Document A — Career Strategy, Evidence & Job Assessment Guide:** the authority for job-fit
  decisions and factual career evidence. It defines evidence confidence, gaps and overclaiming
  constraints. Every assessment receives the complete active Document A and never Document B.
- **Document B — CV Generation & Positioning Guide:** the source of approved CV content and
  instructions for selecting and positioning validated evidence. Required sections are selected
  deterministically for the chosen CV lane. Document B cannot create evidence, strengthen a claim
  beyond Document A or override Document A.

## Core principles

- **Selective applications:** optimise decision quality, not application volume.
- **Human approval:** the user decides whether to pursue a role and approves each CV.
- **Evidence grounding:** Document A controls factual evidence and job-fit logic.
- **Anti-overclaiming:** Document B may position evidence but may not invent or strengthen it beyond the source.
- **Traceability:** store the prompt, document and template versions used for each output.
- **Local-first operation:** SQLite, generated documents and application tracking remain local.
- **No automatic submission:** application submission is explicitly out of scope.

## Technology stack

- Python 3.12+
- Streamlit
- SQLite
- SQLAlchemy 2.x and Alembic
- OpenAI Responses API
- OpenAI Files / vector stores where required
- Pydantic
- python-docx
- pytest
- Ruff
- mypy
- Local Windows execution and Microsoft Word

## Processing model

Assessment and CV generation run through a local background worker. `./dev.ps1 ui` starts the
worker as a separate local process alongside Streamlit and requests a clean worker shutdown when
Streamlit exits. The worker polls for registered work every 60 seconds while idle. The Background
Runs screen refreshes displayed active work every 60 seconds and also provides an explicit refresh
action; both reload durable task status and do not control the worker.
One private worker lease prevents more than one live worker from running at a time. A stale lease
left by a crash is replaced safely on the next startup. After acquiring that lease, the worker
marks tasks left `RUNNING` by its predecessor as `INTERRUPTED`. Interrupted work remains visible
until an explicit retry returns it to `PENDING`; it is never resumed automatically inside a
partially completed handler or model call.

- Default assessment concurrency: `1`
- Default CV-generation concurrency: `1`
- Limited parallelism can be enabled through configuration.
- One failed task must not stop the rest of a batch.

Worker counts are validated in the range `1` through `5`.

## Application configuration

### Environment variables

Configuration is loaded from process environment variables and an optional `.env` file in the
directory where the application is started. Copy `.env.example` to `.env` for local overrides.
The `.env` file and all private data remain excluded from Git.

| Variable | Default |
| --- | --- |
| `JAC_DATA_DIR` | `data` |
| `JAC_DATABASE_PATH` | `<JAC_DATA_DIR>/database/job_application_copilot.db` |
| `JAC_CV_FOLDER` | `<JAC_DATA_DIR>/cvs` |
| `JAC_LOGS_FOLDER` | `<JAC_DATA_DIR>/logs` |
| `JAC_REFERENCE_FOLDER` | `<JAC_DATA_DIR>/reference` |
| `JAC_ASSESSMENT_WORKER_COUNT` | `1` |
| `JAC_CV_WORKER_COUNT` | `1` |
| `JAC_LOG_LEVEL` | `INFO` |
| `JAC_LOG_MAX_SIZE_MB` | `5` |
| `JAC_LOG_BACKUP_COUNT` | `5` |
| `JAC_OPENAI_VECTOR_STORE_TIMEOUT_SECONDS` | `300` |
| `JAC_MINIMUM_FRENCH_REFERENCE_EXAMPLES` | `2` |
| `JAC_DEFAULT_SOURCE` | `LinkedIn` |
| `JAC_DEFAULT_LOCATION` | `UK` |
| `JAC_DEFAULT_LANGUAGE` | `EN` |
| `OPENAI_API_KEY` | unset |

Supported locations are `UK`, `FR` and `CH`; supported languages are `EN` and `FR`. Relative
paths are resolved from the application's working directory. Set `JAC_DATA_DIR` to move all
private application data together. The three specific path variables are optional overrides
for installations that need to store one category elsewhere.

### Private file layout

Private files use the following untracked layout:

```text
data/
├── database/
├── cvs/
├── logs/
└── reference/
    ├── document_a/
    ├── document_b/
    ├── templates/
    ├── examples/
    │   ├── french_resume_example_01.docx
    │   ├── french_resume_example_02.docx
    │   └── french_resume_example_03.docx
    └── prompts/
        ├── assessment/
        └── generation/
            ├── english/
            └── french/
```

The application creates missing directories when it starts. Loading configuration alone does
not modify the filesystem. The example filenames illustrate private local files only; the
application does not create or commit them. Prompt versions are also private runtime assets and
are not committed.

### Settings and asset readiness

The Settings page manages data-driven prompt definitions and private UTF-8 text versions. The
initial configuration contains one assessment prompt, four English-generation stages and two
French-extension stages, but enabled definitions determine the required counts at runtime.
Saving edited text creates a new immutable active version; earlier versions remain available
for explicit rollback.

The same page provides a read-only readiness overview for Documents A and B, the English
and French templates, French CV examples and every enabled prompt group. It shows active
versions and newer inactive candidates separately, including stored filename, version,
upload time and processing status. At least two active ready French examples are required;
additional examples and prompt groups are discovered from stored data rather than capped
in the UI. Set `JAC_MINIMUM_FRENCH_REFERENCE_EXAMPLES` to change that minimum.

### Local asset versioning

Reference DOCX uploads are limited to 5 MiB and are validated as readable DOCX packages before
storage. Each logical asset uses an immutable versioned filename such as
`document-a-v0001.docx`; an existing file is never overwritten. Stored files and their database
metadata remain private under `data/`. Settings provides working upload/replacement controls for
Documents A and B, both templates and dynamic French examples. A validated template or French
example becomes the active `READY` version immediately. A validated Document A or B is retained
as an inactive `PENDING` candidate until its later OpenAI processing succeeds, so the current
active document remains usable. French examples are identified by their user-facing name; the
application derives the internal key and treats the same normalized name as the same versioned
example. Duplicate content is rejected across all French examples. Removing an example excludes
it from readiness but retains its files and metadata so it can be restored.

### OpenAI processing and activation

Canonical Document A and Document B candidates can be uploaded through the OpenAI file-upload
service using the Files API `user_data` purpose. Before upload, the service checks that the
retained file still matches its stored SHA-256 hash. A successful Document A upload stores the
OpenAI file ID and atomically activates that version. A successful Document B upload stores the
file ID before continuing into its vector-store lifecycle. The Document B upload form exposes
this as **Upload and activate with OpenAI**, or **Replace and activate with OpenAI** when a
version already exists. Failed attempts retain the current active version, record a sanitised
processing error and expose **Process and activate** for recovery without uploading an already
stored OpenAI file again. If the local application stops while a version is `PROCESSING`, the
same recovery action resumes from each persisted OpenAI ID; a version interrupted before an ID
was saved restarts that remote step.

For Document B, the vector-store lifecycle creates one store for the uploaded file, waits up to
`JAC_OPENAI_VECTOR_STORE_TIMEOUT_SECONDS` for indexing, and runs a direct validation search.
The candidate becomes active only when indexing is complete and its content is retrievable.
Deactivation of the prior version and activation of the candidate are one database transaction;
failure leaves the prior version active. Inactive and failed stores retain their identifiers and
processed usage bytes for later explicit cleanup. Vector-store indexing does not report model
tokens. A hard process stop in the short interval after OpenAI creates a resource but before its
ID is stored locally can leave an untracked remote resource; safe discovery of those untracked
resources requires a separate ownership-tagging workflow.

### Remote cleanup and restoration

Settings lists tracked OpenAI resources for inactive, non-processing reference versions.
Cleanup requires explicit per-version confirmation, deletes a Document B vector store before
its uploaded file, and deletes only the uploaded file for Document A. Local DOCX files, hashes,
version history and processing status are retained. Successful remote steps are saved
individually so a partial failure can be retried without repeating completed deletion.
An inactive retained Document A or Document B version with no remaining remote identifiers can
be restored without creating a duplicate local version. Restoration rechecks the retained
file's hash, rebuilds its OpenAI resources, and activates it only after the normal validation
workflow succeeds; the current active version remains unchanged if restoration fails.

## Private logs

The application uses rotating UTF-8 structured-text log files. The UI writes to
`data/logs/ui.log`, while the future background worker writes to `data/logs/worker.log` so the
two processes do not compete for the same file. By default, each active log rotates when it
reaches 5 MiB: the current file is archived, a new active file is started, and the five most
recent backups are retained.

Log timestamps use UTC to whole seconds. Set `JAC_LOG_LEVEL` to `DEBUG`, `INFO`, `WARNING`,
`ERROR` or `CRITICAL`. Use `JAC_LOG_MAX_SIZE_MB` to change the rotation threshold and
`JAC_LOG_BACKUP_COUNT` to change the number of retained backups.

Logs are private application data. They may contain job descriptions, CV content, prompts,
Documents A and B, model inputs and outputs, personal information, local paths, identifiers,
timings and errors. The complete `data/logs` directory is excluded from Git. Do not publish
or share logs without reviewing and sanitising them.

Persisted assessment and background-task error messages are intended for this local-only
application and may include provider or processing details. They are not guaranteed to be
sanitised for publication. Review and redact database contents and logs before sharing them or
adapting the application for hosted or multi-user use.

API keys, authentication tokens, passwords, authorization headers and other secrets must
never be logged. The configured OpenAI API key is redacted if its exact value accidentally
appears in a log record, but this is a safety net rather than a substitute for careful logging.

## Document strategy

- Document A and Document B are maintained as DOCX.
- The complete active Document A is supplied to every assessment call.
- The user confirms the assessment-recommended CV lane; a versioned routing table then selects
  mandatory Document B sections. Optional vector retrieval is limited to that authorised scope and
  may only add supplementary CV material.
- The two French prompts are additional stages after the four English CV-generation prompts.
- English and French templates remain local DOCX files.

## Generated CV naming

All system-generated CVs are stored in one configured folder:

```text
resume - Daniel Brule - <YYYY-MM-DD> - <Company>.docx
```

Invalid Windows filename characters are sanitised. A numeric suffix prevents accidental overwrite.

## Documentation

- [Requirements](docs/requirements.md)
- [Screens](docs/screens.md)
- [Data model](docs/data-model.md)
- [Architecture](docs/architecture.md)
- [OpenAI pipeline](docs/openai-pipeline.md)
- [Document B section-aware retrieval](docs/document-b-retrieval.md)
- [Document B lane-routing setup and template](docs/document-b-routing-manifest.md)
- [Codex workflow](docs/codex-workflow.md)
- [Roadmap and issue workflow](docs/backlog.md)
- [Architecture decisions](docs/decisions/)

## Status

Implementation is in progress. Delivery is managed through GitHub Issues and validated by
GitHub Actions. The Streamlit application supports manual job entry and editing through a
sortable, selectable and filterable Jobs dashboard. Prompt definitions, editing, completeness
and version activation are available on Settings alongside a complete local asset readiness
overview and validated DOCX replacement controls. OpenAI reference file upload, identifier
persistence and Document B vector-store processing and activation are available from Settings.
Background Runs shows filterable batch and task state, retained execution-attempt history, errors
and guarded retry actions.

## Development

### Prerequisites

Requirements:

- Python 3.12 or later
- Poetry 2.x

If the current shell blocks local PowerShell scripts, allow them for that shell session only:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

### Environment setup

Create or update the project environment:

```powershell
.\dev.ps1 env
```

Activate it in the current PowerShell session when an interactive environment is useful:

```powershell
. .\dev.ps1 activate
```

### Local data and database

Create missing private directories and validate existing paths without starting the UI:

```powershell
.\dev.ps1 directories
```

Create or upgrade the private SQLite database and display its migration and health status:

```powershell
.\dev.ps1 database
```

The database uses Alembic for ordered schema migrations. SQLite runs in WAL mode with foreign
keys enabled and a five-second busy timeout. The private database records its installed
revision in `alembic_version`; committed scripts under
`src/job_application_copilot/repositories/migrations/versions` define available revisions.

Preview the migrations as SQL without creating directories, connecting to SQLite, or changing
the database:

```powershell
.\dev.ps1 database-sql
```

Inspect the current validated Document B routing manifest without changing data or making model
calls:

```powershell
.\dev.ps1 document-b-routing
.\dev.ps1 document-b-routing -DocumentBVersion 3
.\dev.ps1 document-b-routing -DocumentBVersion 3 -Lane HEAD_OF_SOLUTIONS_ARCHITECTURE
```

Each installation keeps its editable routing file at
`data/reference/routing/document-b-lane-routes.yaml`. Copy the committed
[`templates/document-b-lane-routes.template.yaml`](templates/document-b-lane-routes.template.yaml)
there and customise it for that installation's Document B before processing the document.
Those configured lane keys are also the allowed primary and secondary role-family values returned
by assessment; no source-code enum needs changing for another installation.

See [Document B lane-routing manifest](docs/document-b-routing-manifest.md) for first-time setup,
the complete YAML structure, review process and the distinction between direct context and
vector-search scopes.

Reset every stored reference-asset version during development:

```powershell
.\dev.ps1 reset-reference-assets -Force
```

This removes tracked local reference files and their `reference_assets` rows. When stored
metadata identifies OpenAI files or vector stores, those remote resources are deleted first.
Prompt definitions, jobs and unrelated private data are preserved.

### Automated checks

Run the automated checks:

```powershell
.\dev.ps1 test
.\dev.ps1 coverage
.\dev.ps1 lint
.\dev.ps1 type
.\dev.ps1 worker
```

`coverage` runs the complete test suite with branch coverage and reports missing lines. It
establishes visibility without enforcing a percentage threshold. `type` checks the production
package with mypy. CI runs both checks in addition to the normal test, lint and format checks.

| Target | Scope | External side effects | Required in CI |
| --- | --- | --- | --- |
| `test` | Complete automated pytest suite except opt-in integrations | Local temporary files and SQLite databases only | Yes |
| `coverage` | Same suite with branch coverage and missing-line reporting | Local temporary files and SQLite databases only | Yes |
| `lint` | Ruff lint and format checks for the repository | None | Yes |
| `type` | mypy analysis of `src/job_application_copilot` | None | Yes |
| `test-openai` | Real OpenAI file and vector-store integration tests | Creates and then deletes billable remote resources | No; explicit opt-in |
| `ui` | Interactive Streamlit application for manual verification | Reads and writes configured private data; may call OpenAI after an explicit user action | No; run for UI changes |

The real OpenAI integration tests are intentionally excluded unless explicitly enabled. They
upload temporary DOCX files; the vector-store test also indexes, searches and activates a
temporary Document B version. All created remote files and stores are deleted during cleanup:

```powershell
.\dev.ps1 test-openai
```

`OPENAI_API_KEY` must be available in `.env` or the process environment. Ordinary test and CI
runs skip this external test and never contact OpenAI. The explicit target temporarily enables
the integration marker for its child test process and restores the previous environment afterward.

### Run the application

Start the Streamlit application:

```powershell
.\dev.ps1 ui
```

### Troubleshooting commands

Run `.\dev.ps1 help` to list all supported targets. The underlying Poetry commands remain
available for troubleshooting:

```powershell
poetry install
poetry run pytest
poetry run pytest --cov=job_application_copilot --cov-branch --cov-report=term-missing
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy
poetry run streamlit run src/job_application_copilot/ui/app.py
```

The developer-script test targets automatically use a unique writable directory below
`.pytest-tmp`. When invoking pytest directly in a restricted environment, provide an equivalent
project-local base directory:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-tmp/local
```

This avoids failures when the host denies access to the user-profile temporary directory.
When invoking `dev.ps1` from another working directory, pass its absolute path; the script
resolves project commands and check paths from its own repository location.

## Importing the backlog into GitHub Issues

The backlog CSV can be imported into GitHub Issues with GitHub CLI. GitHub Issues is the
operational source of truth; the tracked CSV provides a compact overall view and import source.

Prerequisites:

1. Install [GitHub CLI](https://cli.github.com/).
2. Authenticate with `gh auth login`.
3. Run commands from a checkout whose Git remote points to the target repository, or pass
   `-Repository OWNER/REPO` explicitly.

Preview the import without contacting or changing GitHub:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\import-backlog.ps1 -DryRun
```

Import all tickets except those whose CSV status is `DONE`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\import-backlog.ps1 -Repository OWNER/REPO
```

Add `-IncludeCompleted` to include `DONE` tickets. The importer creates missing milestones
and labels and skips tickets whose ticket ID already appears in an existing issue title.
It can therefore be rerun safely after a partial failure.

To preview or import one ticket, add `-TicketId T1.1`.

Run the offline importer checks with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-import-backlog.ps1
```
