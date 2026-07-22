# Working with Codex

## Recommended unit of work

Use one ticket, one branch and one review at a time.

A good ticket should normally:

- change a limited set of files;
- implement one observable capability;
- add focused tests;
- be understandable from one Git diff;
- avoid adjacent backlog items.

Ticket size labels:

- `XS`: typically under 100 changed lines
- `S`: typically 50–250 changed lines
- `M`: potentially 150–500 changed lines and should be split if the plan reveals multiple independent changes

These are guidance, not quotas.

## Step 1 — Ask for a plan

```text
Review ticket <ID>.

Read AGENTS.md and the relevant documents under docs/.
Inspect the existing implementation.

Do not modify files yet.

Return:
1. Your understanding of the requirement
2. Files you expect to modify
3. Proposed implementation
4. Tests you will add or update
5. Ambiguities, risks or assumptions
6. Estimated change size
```

Review the plan before permitting implementation.

## Step 2 — Implement only the ticket

```text
Implement ticket <ID> according to the approved plan.

Constraints:
- Implement only this ticket.
- Do not implement adjacent backlog items.
- Keep the change as small as possible.
- Follow AGENTS.md.
- Add or update tests.
- Run relevant tests and quality checks.
- Do not commit automatically.

At the end, report:
1. Files changed
2. Main implementation decisions
3. Tests run and results
4. Remaining limitations
5. Manual verification steps
```

## Step 3 — Review

Review:

- Git diff;
- dependencies;
- migrations;
- test changes;
- affected screen;
- whether unrelated files changed;
- whether the ticket acceptance criteria are met.

Ask for a narrow correction rather than restarting a broad task.

## Step 4 — Commit

Commit only after:

- automated checks pass;
- manual verification is complete;
- scope is correct;
- documentation is updated where required.

Suggested commit format:

```text
<TICKET-ID> <imperative summary>
```

Example:

```text
T2.3 add job entry form
```

## Practical controls

- Start with planning-only prompts.
- Keep the working tree clean before each ticket.
- Do not combine database migration, UI, OpenAI integration and rendering in one ticket.
- Ask Codex to explain any new dependency before adding it.
- For model-call tickets, inspect the exact request context before live execution.
- For DOCX tickets, open the generated file manually in Word.
