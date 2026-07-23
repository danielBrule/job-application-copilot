# AGENTS.md

## Project identity

`job-application-copilot` is an **evidence-grounded career decision and document-generation workflow**.

It is not a mass-application system. Never add automatic application submission, employer-portal automation, bulk outreach or features whose primary purpose is increasing application volume.

## Read before changing code

1. `docs/requirements.md`
2. `docs/screens.md`
3. `docs/data-model.md`
4. `docs/architecture.md`
5. `docs/openai-pipeline.md`
6. The relevant GitHub issue; use `docs/backlog.md` for milestone context
7. Relevant files under `docs/decisions/`

## Non-negotiable rules

- Human approval is required before CV generation and before a CV is marked approved.
- Document A controls job-fit logic, factual evidence, evidence confidence and overclaiming constraints.
- Document B positions validated evidence but must not create evidence or override Document A.
- Supply the complete active Document A to assessment calls.
- Route Document B deterministically by the selected lane; semantic retrieval is supplementary only.
- French CV generation runs the four English stages followed by two additional French stages.
- Never convert prototype, self-directed, shared or adjacent evidence into production or sole-ownership claims.
- Never invent dates, employers, titles, metrics, technologies or outcomes.
- Never submit an application automatically.
- Keep all private career documents, generated CVs, SQLite databases, logs and secrets out of Git.
- Never log API keys, authentication tokens, passwords or authorization headers.

## Delivery discipline

Work on one ticket at a time.

Before implementation:
- inspect the repository;
- explain the requirement;
- list files to change;
- propose tests;
- identify assumptions;
- do not modify files until the plan is approved.

During implementation:
- implement only the approved ticket;
- avoid adjacent backlog work;
- keep changes small and reviewable;
- add or update tests;
- run relevant checks;
- do not commit automatically.

At completion report:
1. files changed;
2. main decisions;
3. tests run and results;
4. limitations;
5. manual verification steps.

## Coding standards

- Python 3.12+ and type hints.
- Small functions and explicit domain enums.
- Pydantic validation at external boundaries.
- Business logic outside Streamlit page code.
- Database access through repositories/services.
- Model calls through one OpenAI client abstraction.
- Prompts stored and versioned outside UI code.
- Structured exceptions and actionable user-facing errors.
- Sequential processing by default; configurable concurrency must remain bounded.
- No microservices or unnecessary infrastructure.

## Required checks

Use the repository commands documented in `README.md`:

```powershell
.\dev.ps1 help
.\dev.ps1 env
. .\dev.ps1 activate
.\dev.ps1 directories
.\dev.ps1 test
.\dev.ps1 lint
.\dev.ps1 ui
```

At minimum, run `test` and `lint` before completing a ticket. Run focused checks first, then
the broader suite. Use `ui` for manual verification when the interface is affected.
