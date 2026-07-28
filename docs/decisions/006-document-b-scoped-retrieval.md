# ADR-006 — Document B scoped routing and retrieval

## Status

Accepted

## Decision

- Phase 1 uses Document A only and recommends a controlled CV lane; the user confirms or changes
  that lane before Document B selection.
- A versioned SQLite routing set, bound to one exact Document B version, maps each lane to local
  section IDs and routing roles.
- Local section-tree lookup supplies all mandatory Document B material.
- Vector retrieval is supplementary and may search only section-derived records whose section IDs
  are authorised by the active routing set.
- Phase 2 persists the selected local sections, optional retrieved passages and guardrails in a
  structured CV-generation brief. Human approval of that brief is required before Phase 3.
- Phase 3 and Phase 4 reuse the approved brief and selected material. They do not independently
  perform a broad search over Document B.

## Rationale

Document B contains rules, positioning material and a bullet library that must be applied
predictably. Whole-document semantic retrieval cannot guarantee that a mandatory rule is included
or that a returned chunk belongs to an authorised lane. Deterministic routing provides control,
reproducibility and traceability. Scoped retrieval retains flexibility for job-specific optional
material without allowing it to override Document A or mandatory Document B content.

## Consequences

- A complete-DOCX vector index alone is insufficient for generation retrieval; the target index
  must carry exact Document B version and local section-ID scope.
- New Document B versions require routing-set validation before activation.
- Generation traceability includes the routing-set version, selected section IDs, retrieved passage
  IDs and guardrail IDs.
- The routing configuration and section-scoped index require dedicated implementation tickets.
