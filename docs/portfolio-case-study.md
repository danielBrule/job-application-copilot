# Portfolio case study

## The problem

Tailoring a CV is a high-stakes writing task: an attractive result can still be inaccurate,
untraceable or based on the wrong interpretation of a role. This project treats the task as a
controlled decision-and-document workflow, rather than as a text-generation shortcut.

It helps one user record opportunities locally, assess whether they are worth pursuing, generate
a tailored English or French DOCX CV after explicit approval, and retain the information needed to
review how that output was produced.

It deliberately does not automate applications, employer portals or outreach.

## Design choices

| Concern | Design | Reason |
| --- | --- | --- |
| Factual grounding | The complete active Document A is supplied to each assessment. | Job-fit logic, evidence confidence and overclaiming constraints cannot be lost through selective retrieval. |
| CV positioning | The user-confirmed lane deterministically selects Document B sections. | Model interpretation cannot silently choose the primary career narrative. |
| Retrieval | Vector search is optional and constrained to the authorised Document B section scope. | Retrieval can improve relevance without creating evidence or overriding mandatory content. |
| Model reliability | Responses use structured outputs and are validated locally with Pydantic. | Invalid model output is rejected at the boundary rather than trusted by the UI. |
| Human control | Generation and final CV approval are explicit user actions. | A model cannot create a final candidate document or submit an application on its own. |
| Failure recovery | Background work uses durable SQLite tasks, execution-attempt history, bounded workers and guarded retries. | A crash leaves work visible and retryable rather than resuming an uncertain partial model call. |
| Privacy | Documents, generated CVs, SQLite state and logs remain local and Git-ignored. | Personal career data stays out of the public repository by default. |

## Architecture

The application is a modular local monolith: Streamlit components remain thin; application
services own use-case orchestration; repositories own SQLite access; the OpenAI adapter is behind
capability-specific protocols; and DOCX processing, typed configuration and observability have
separate responsibilities. Alembic governs schema evolution.

The provider-specific production adapter currently targets OpenAI. Its capability protocols keep
the application boundary narrow enough that another model provider could be introduced without
moving provider concerns into the UI, domain logic or repositories. A replacement would still need
to meet the same structured-output, file/reference and observability contracts.

For the full implementation view, see [Architecture](architecture.md) and the
[OpenAI pipeline](openai-pipeline.md).

## AI assurance model

The key assurance property is evidence control, not merely prompt wording:

1. Document A is the source of truth for assessment facts, evidence confidence and constraints.
2. The assessment receives all of active Document A, job metadata and the complete job description.
3. The user confirms or changes the recommended CV lane.
4. The selected lane authorises Document B sections through a versioned routing manifest.
5. Generation persists stage inputs and uses the authorised content plus guardrails.
6. A person reviews and explicitly approves the final CV before it is marked approved.

The result is reproducible enough to inspect which prompt, reference version, template, routing
set and model configuration influenced an output. It does not claim that an LLM can prove a CV is
factually correct; the workflow preserves human accountability for that decision.

## Engineering evidence

- Python 3.12, typed Pydantic boundaries, SQLAlchemy and Alembic.
- A local worker with bounded configurable concurrency and a single-worker lease.
- Retained task attempts, interruption handling and explicit retries.
- Rotating local logs with secret redaction safeguards.
- GitHub Actions on Windows runs tests, branch-coverage reporting, Ruff lint/format checks and
  mypy type checks.
- Real OpenAI integration tests are opt-in because they create billable remote resources.

## What would be needed for a hosted production service

The existing application is production-minded within its local-first scope. A hosted,
multi-user production service would additionally require:

- identity, authorisation, tenant isolation and audited access controls;
- encrypted managed storage, retention/deletion policies and tested backup/restore procedures;
- deployment packaging, environment promotion, rollback and secret-management practices;
- service monitoring, alerting, on-call ownership and incident runbooks;
- dependency and supply-chain scanning, vulnerability response and release governance;
- provider failover policy, quota/cost controls and end-to-end resilience testing;
- legal and privacy review appropriate to the jurisdictions and personal data processed.

These are intentional non-goals of the present repository, not hidden claims of completion.
