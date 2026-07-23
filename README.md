# Job Application Copilot

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

Install the project and its development dependencies. Poetry creates the project environment
at `.venv`:

```powershell
poetry install
```

Run the automated checks:

```powershell
poetry run pytest
poetry run ruff check .
poetry run ruff format --check .
```

Start the Streamlit application:

```powershell
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
