# Documentation index

The root [README](../README.md) is the fast portfolio overview. This index directs readers to the
level of detail they need.

## Start here

| If you want to understand | Read |
| --- | --- |
| The portfolio story, workflow and scope | [Root README](../README.md) |
| Engineering choices, assurance controls and the hosted-service gap | [Portfolio case study](portfolio-case-study.md) |
| A repeatable product walkthrough using fictional data | [Five-minute demo](demo.md) |
| Installation, configuration, developer commands and safe operation | [Local operations](local-operations.md) |

## Product and implementation reference

- [Requirements](requirements.md) — functional rules and business constraints.
- [Screens](screens.md) — UI behaviour and workflow expectations.
- [Data model](data-model.md) — entities, validation, persistence and relationships.
- [Architecture](architecture.md) — module responsibilities, worker model, integration boundaries
  and security constraints.
- [OpenAI pipeline](openai-pipeline.md) — model calls, structured outputs, routing, generation and
  usage tracking.
- [Document B retrieval](document-b-retrieval.md) — section-aware supplementary retrieval.
- [Document B routing manifest](document-b-routing-manifest.md) — deterministic lane routing and
  the editable configuration template.
- [Architecture decisions](decisions/) — accepted technical decisions and consequences.

## Delivery and contributor workflow

- [Roadmap and issue workflow](backlog.md) — milestones, tickets and issue import.
- [Codex workflow](codex-workflow.md) — focused ticket and review process.
- [Ticket template](ticket-template.md) — issue structure.
- [Security and privacy](../SECURITY.md) — local data boundary and safe vulnerability reporting.

## Public portfolio assets

- [Fictional demo inputs](../examples/portfolio-demo/fictional-inputs.md) — safe source data for
  a manual demonstration.
- [Screenshot guidance](images/README.md) — public-image redaction rules.
