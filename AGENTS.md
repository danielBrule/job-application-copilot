# AGENTS.md

## Project identity

`job-application-copilot` is an **evidence-grounded career decision and document-generation workflow**.

It is not a mass-application system. Never add automatic application submission, employer-portal automation, bulk outreach, or features whose primary purpose is increasing application volume.

## Working principles

- Work on one ticket at a time.
- Keep changes small, focused, and reviewable.
- Use the current GitHub issue as the primary statement of scope.
- Inspect only the documentation and repository areas relevant to the ticket.
- Reuse information already established in the current conversation.
- Do not reread unchanged documents or rescan the full repository without a clear reason.
- Ask for clarification when an ambiguity could materially affect behaviour, data, architecture, or acceptance criteria.
- Do not implement adjacent improvements unless they are required to complete the approved ticket.

## Read before changing code

Always read:

1. This `AGENTS.md`.
2. The relevant GitHub issue.

Then read only the documentation sections directly relevant to the ticket:

- `docs/requirements.md` for functional requirements and business rules.
- `docs/screens.md` for UI behaviour and workflow expectations.
- `docs/data-model.md` for entities, fields, validation, persistence, and relationships.
- `docs/architecture.md` for application structure and component responsibilities.
- `docs/openai-pipeline.md` for model calls, prompts, routing, evaluation, and generation workflows.
- `docs/backlog.md` only when milestone context or dependency information is required.
- Relevant files under `docs/decisions/` when the ticket touches a recorded architectural or product decision.

Do not automatically read every document in full.

Read complete documents only when the ticket:

- introduces or changes architecture;
- changes a cross-cutting domain rule;
- affects several workflows or application layers;
- modifies the data model substantially;
- changes the OpenAI pipeline;
- conflicts with an existing documented decision;
- cannot be understood reliably from targeted sections.

When inspecting the repository:

- begin with targeted searches for relevant pages, services, models, repositories, schemas, and tests;
- inspect direct callers and dependencies of the code likely to change;
- expand the investigation only when evidence shows that broader inspection is necessary;
- do not scan unrelated directories, historical commits, or generated files by default.

## Non-negotiable rules

- Human approval is required before CV generation and before a CV is marked approved.
- Document A controls job-fit logic, factual evidence, evidence confidence, and overclaiming constraints.
- Document B positions validated evidence but must not create evidence or override Document A.
- Supply the complete active Document A to assessment calls.
- Route Document B deterministically by the selected lane; semantic retrieval is supplementary only.
- French CV generation runs the four English stages followed by two additional French stages.
- Never convert prototype, self-directed, shared, or adjacent evidence into production or sole-ownership claims.
- Never invent dates, employers, titles, metrics, technologies, or outcomes.
- Never submit an application automatically.
- Keep all private career documents, generated CVs, SQLite databases, logs, and secrets out of Git.
- Never log API keys, authentication tokens, passwords, or authorization headers.

## Delivery discipline

### Before implementation

Inspect the ticket, relevant documentation, and relevant repository files.

Do not modify files yet.

Return a concise plan containing:

1. Understanding of the ticket.
2. Files expected to be created or modified.
3. Proposed implementation.
4. Tests to add or update.
5. Material assumptions, ambiguities, or inconsistencies.

Keep the response focused on decisions that require review.

Do not provide lengthy summaries of documents or code unless they reveal an important constraint or conflict.

Wait for approval before implementation.

### During implementation

- Continue in the same conversation when possible.
- Reuse the approved plan and previously inspected context.
- Do not reread unchanged documents unless implementation reveals a genuine uncertainty.
- Implement only the approved ticket.
- Avoid adjacent backlog work and speculative refactoring.
- Preserve existing conventions unless the ticket requires a deliberate change.
- Keep business logic outside Streamlit page code.
- Add or update tests alongside the implementation.
- Run focused tests first.
- Fix only failures caused by, or directly blocking, the ticket.
- Do not commit automatically.

When implementation evidence requires a material departure from the approved plan:

1. stop before making the material change;
2. explain the new evidence;
3. propose the revised approach;
4. request approval.

Minor implementation details that do not alter scope, behaviour, architecture, or risk do not require another approval step.

### At completion

Report concisely:

1. Files changed.
2. Main implementation decisions.
3. Tests and checks run, including results.
4. Known limitations or unresolved issues.
5. Manual verification steps.
6. Recommended file order for review.

Do not repeat the original ticket or provide a long narrative of the implementation.

## Context and usage efficiency

Use repository and model context deliberately.

- Prefer targeted file searches over broad repository scans.
- Prefer relevant sections over reading complete documents.
- Do not repeatedly inspect files already read unless they have changed or new evidence requires it.
- Do not reproduce large files in responses.
- Summarise relevant findings instead of quoting long blocks.
- Do not inspect Git history unless the current implementation cannot be understood without it.
- Do not inspect unrelated open issues or pull requests.
- Do not run the same search repeatedly without changing the query or investigation goal.
- Do not run full test suites before focused tests when a smaller test selection can identify implementation problems faster.
- Do not rerun successful checks unless code relevant to those checks has subsequently changed.
- Keep planning and completion responses concise.
- Use the simplest implementation that satisfies the approved ticket and existing architecture.

Efficiency must not override correctness, validation, security, or the non-negotiable rules.

## Coding standards

- Python 3.12+ and type hints.
- Small functions and explicit domain enums.
- Pydantic validation at external boundaries.
- Business logic outside Streamlit page code.
- Database access through repositories and services.
- Model calls through one OpenAI client abstraction.
- Prompts stored and versioned outside UI code.
- Structured exceptions and actionable user-facing errors.
- Sequential processing by default.
- Configurable concurrency must remain bounded.
- No microservices or unnecessary infrastructure.
- Follow existing naming, module, test, and dependency patterns.
- Avoid adding dependencies when the existing stack can solve the requirement cleanly.
- Avoid broad refactoring within feature tickets unless required for correctness.

## Validation and error handling

- Validate data at the appropriate external or domain boundary.
- Keep domain validation independent from Streamlit-specific behaviour.
- Provide actionable user-facing validation messages.
- Do not silently discard invalid values.
- Preserve existing defaults only when the final submitted value remains valid.
- Use structured exceptions for expected application failures.
- Do not expose secrets, internal traces, or sensitive document content in UI errors or logs.
- Test both successful and unsuccessful paths for changed behaviour.

## Testing expectations

Tests should be proportionate to the ticket and should normally cover:

- changed domain rules;
- changed service or repository behaviour;
- changed external-boundary validation;
- changed Streamlit workflow behaviour;
- regressions identified during implementation.

Prefer extending existing test modules rather than creating parallel test structures.

Avoid duplicating the same assertion across several layers unless each layer has a distinct responsibility.

For bug fixes, add a regression test that fails before the fix and succeeds afterwards whenever practical.

## Required checks

Use the repository commands documented in `README.md`.

Run focused tests directly with `pytest` when practical, then use the developer script for the required repository checks.

```powershell
.\dev.ps1 test
.\dev.ps1 lint
.\dev.ps1 type
.\dev.ps1 ui