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
- [Implementation backlog](docs/backlog.md)
- [Architecture decisions](docs/decisions/)

## Status

Specification and implementation backlog complete. Application implementation has not started.
