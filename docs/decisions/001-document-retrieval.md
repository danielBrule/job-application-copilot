# ADR-001 — Document retrieval strategy

## Status

Accepted

## Decision

- Supply the complete active Document A to every assessment call.
- Do not split or semantically filter Document A in the MVP.
- Maintain Document B as one DOCX.
- Extract Document B headings locally.
- Route mandatory B sections deterministically from the selected CV lane.
- Permit semantic retrieval only as supplementary context.
- Use French reference CVs for style and terminology, never factual evidence.

## Rationale

Document A is compact enough to include in full and contains interdependent strategy, evidence and risk rules. Missing a section could materially change a job decision.

Document B explicitly supports lane-based use. Deterministic section routing gives predictable coverage and traceability while avoiding the cost and confusion of sending the entire long document to every stage.

## Consequences

- Assessment requests have a larger but stable input.
- Document B requires reliable heading extraction and lane configuration.
- Every generated CV can record the exact B sections and supplementary chunks used.
