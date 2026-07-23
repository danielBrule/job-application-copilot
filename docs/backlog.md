# Roadmap and issue workflow

GitHub Issues is the operational source of truth for implementation work:

- [All issues](https://github.com/danielBrule/job-application-copilot/issues)
- [Milestones](https://github.com/danielBrule/job-application-copilot/milestones)

`implementation-backlog.csv` provides a compact overall view and the source used by the
issue-import script. Detailed scope, dependencies, acceptance criteria and discussion belong
in GitHub Issues rather than being duplicated in this document.

Agents should read the relevant GitHub issue for ticket-level requirements. Individual ticket
sections are intentionally not maintained in this document and should not be expected here.

Status values are `TODO`, `IN_PROGRESS`, `BLOCKED`, `DONE` and `DEFERRED`.

## Delivery sequence

### M0 — Specification

Establish the requirements, screen specification, architecture, decisions and issue-led
delivery workflow.

### M1 — Foundation

Create the Python project, developer tooling, typed configuration, private local directories,
database foundation and Streamlit navigation shell.

### M2 — Job management

Implement job persistence, entry, editing, listing and filtering.

### M3 — Reference assets

Implement versioned local and remote handling for documents, prompts, templates and French
reference material.

### M4 — Background processing

Implement durable batches, tasks, worker execution, recovery and run monitoring.

### M5 — Assessment

Implement evidence-grounded job assessment, structured validation, stale-result handling and
human decisions.

### M6 — Dashboard and KPIs

Complete the operational Jobs dashboard, filters, selections and usage/time indicators.

### M7 — English CV generation

Implement deterministic context assembly, the four-stage English pipeline, validation,
rendering and background execution.

### M8 — CV review and upload

Support existing-CV upload, Word opening and explicit human approval.

### M9 — French generation

Extend the complete English pipeline with the two additional French stages and French DOCX
rendering.

### M10 — Application tracking

Implement contacts, application fields and dashboard tracking.

### M11 — Hardening and delivery

Complete launch tooling, validation, error handling, end-to-end tests, operating guidance and
the final privacy audit.

## Working a ticket

Use one GitHub issue, one branch and one review at a time. Before implementation, inspect the
issue and relevant documentation, propose a plan, and wait for approval. During implementation,
stay within the approved issue, add focused tests and do not commit automatically.

See [Working with Codex](codex-workflow.md) for the complete workflow.
