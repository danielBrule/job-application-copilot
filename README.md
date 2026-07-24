# Job Application Copilot

[![CI](https://github.com/danielBrule/job-application-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/danielBrule/job-application-copilot/actions/workflows/ci.yml)

An **evidence-grounded career decision and document-generation workflow** for assessing opportunities, selecting applications deliberately, and producing traceable, reviewable CVs.

The project is intentionally **not an automated mass-application tool**. It does not submit applications, automate employer portals, or remove human approval from career decisions.

## What it does

1. Stores job descriptions and basic job information locally.
2. Assesses selected jobs using Document A.
3. Displays structured assessments for human review.
4. Lets the user select jobs for CV generation or upload an existing CV.
5. Generates English or French DOCX CVs using Document B, configured prompts and fixed templates.
6. Opens the DOCX directly in Microsoft Word for manual editing.
7. Records explicit CV approval.
8. Tracks application status, contacts, interviews, notes and next actions.
9. Reports simple workflow, token and processing-time KPIs.

## Core principles

- **Selective applications:** optimise decision quality, not application volume.
- **Human approval:** the user decides whether to pursue a role and approves each CV.
- **Evidence grounding:** Document A controls factual evidence and job-fit logic.
- **Anti-overclaiming:** Document B may position evidence but may not invent or strengthen it beyond the source.
- **Traceability:** store the prompt, document and template versions used for each output.
- **Local-first operation:** SQLite, generated documents and application tracking remain local.
- **No automatic submission:** application submission is explicitly out of scope.

## Agreed stack

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
- Local Windows execution and Microsoft Word

## Processing model

Assessment and CV generation run through a local background worker.

- Default assessment concurrency: `1`
- Default CV-generation concurrency: `1`
- Limited parallelism can be enabled through configuration.
- One failed task must not stop the rest of a batch.

Worker counts are validated in the range `1` through `5`.

## Application configuration

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
| `JAC_DEFAULT_SOURCE` | `LinkedIn` |
| `JAC_DEFAULT_LOCATION` | `UK` |
| `JAC_DEFAULT_LANGUAGE` | `EN` |
| `OPENAI_API_KEY` | unset |

Supported locations are `UK`, `FR` and `CH`; supported languages are `EN` and `FR`. Relative
paths are resolved from the application's working directory. Set `JAC_DATA_DIR` to move all
private application data together. The three specific path variables are optional overrides
for installations that need to store one category elsewhere.

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
    └── examples/
        ├── french_resume_example_01.docx
        ├── french_resume_example_02.docx
        └── french_resume_example_03.docx
```

The application creates missing directories when it starts. Loading configuration alone does
not modify the filesystem. The example filenames illustrate private local files only; the
application does not create or commit them.

Prompt versions are also private runtime assets:

```text
data/reference/prompts/
├── assessment/
└── generation/
    ├── english/
    └── french/
```

Prompt files are not committed.

## Private logs

The UI writes UTF-8 structured text to `data/logs/ui.log`. The future background worker uses
the same format in `data/logs/worker.log` so the processes do not compete while rotating one
file. Each active file rotates at 5 MiB and retains five backups. Log timestamps use UTC to
whole seconds. Set `JAC_LOG_LEVEL` to `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`.
Use `JAC_LOG_MAX_SIZE_MB` and `JAC_LOG_BACKUP_COUNT` to adjust retention.

Logs are private application data. They may contain job descriptions, CV content, prompts,
Documents A and B, model inputs and outputs, personal information, local paths, identifiers,
timings and errors. The complete `data/logs` directory is excluded from Git. Do not publish
or share logs without reviewing and sanitising them.

API keys, authentication tokens, passwords, authorization headers and other secrets must
never be logged. The configured OpenAI API key is redacted if its exact value accidentally
appears in a log record, but this is a safety net rather than a substitute for careful logging.

## Document strategy

- Document A and Document B are maintained as DOCX.
- The complete active Document A is supplied to every assessment call.
- Document B is routed deterministically by CV lane, with optional supplementary semantic retrieval.
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
- [Codex workflow](docs/codex-workflow.md)
- [Roadmap and issue workflow](docs/backlog.md)
- [Architecture decisions](docs/decisions/)

## Status

Foundation implementation is in progress. Delivery is managed through GitHub Issues and
validated by GitHub Actions.

## Development

Requirements:

- Python 3.12 or later
- Poetry 2.x

If the current shell blocks local PowerShell scripts, allow them for that shell session only:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

Create or update the project environment:

```powershell
.\dev.ps1 env
```

Activate it in the current PowerShell session when an interactive environment is useful:

```powershell
. .\dev.ps1 activate
```

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

Run the automated checks:

```powershell
.\dev.ps1 test
.\dev.ps1 lint
```

Start the Streamlit application:

```powershell
.\dev.ps1 ui
```

Run `.\dev.ps1 help` to list all supported targets. The underlying Poetry commands remain
available for troubleshooting:

```powershell
poetry install
poetry run pytest
poetry run ruff check .
poetry run ruff format --check .
poetry run streamlit run src/job_application_copilot/ui/app.py
```

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
