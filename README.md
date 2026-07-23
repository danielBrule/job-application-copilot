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
- SQLAlchemy or SQLModel
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
| `JAC_REFERENCE_FOLDER` | `<JAC_DATA_DIR>/reference` |
| `JAC_ASSESSMENT_WORKER_COUNT` | `1` |
| `JAC_CV_WORKER_COUNT` | `1` |
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
└── reference/
    ├── document_a/
    ├── document_b/
    ├── templates/
    └── examples/
        └── french_resume_example.docx
```

The application does not create these directories while merely loading configuration.

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

Specification and implementation backlog complete. Application implementation has not started.

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
