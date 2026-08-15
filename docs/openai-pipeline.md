# OpenAI prompting and document pipeline

## Assessment pipeline

```text
Assessment prompt
+ Complete active Document A
+ Job metadata
+ Full JD
+ Structured-output schema
→ Structured assessment
```

Document A is the sole career-strategy and evidence source for assessment. Document B is prohibited at this stage.
The prepared Document A input is the complete uploaded DOCX referenced by its OpenAI file ID;
its exact local version and hash accompany the request metadata. Document A is never split,
semantically filtered or replaced by locally extracted fallback text.

The result includes both user-visible assessment fields and an internal handover:

- recommended CV lane;
- secondary angle;
- evidence anchors;
- evidence confidence;
- evidence gaps;
- overclaiming constraints.
- material mandate dimensions, their Document A evidence strength and whether they should shape CV selection.

## Document B routing and retrieval

Document B is the controlled CV-generation library. It is not sent in full to the model for every
CV. The workflow combines deterministic local routing for mandatory content with vector retrieval
for optional, job-specific CV material and bullet selection. Document B never creates factual
evidence or overrides Document A.

### Phase 1 — recommend and confirm the CV lane

Phase 1 receives the job description, complete Document A and the assessment prompt. It does not
receive Document B content. The assessment returns a controlled, data-driven lane identifier, such
as `HEAD_OF_SOLUTIONS_ARCHITECTURE`, together with evidence to emphasise, evidence to downplay,
risks and overclaiming guardrails, and any secondary angle.

The assessment recommends the lane; before Phase 2, the user confirms or changes it. The confirmed
selected lane controls all subsequent Document B routing.

Primary role family, optional secondary role family and recommended lane use the same identifiers.
The assessment structured-output schema restricts non-null values to the lane keys from the active
validated routing set; local Pydantic validation repeats that membership check.

Material mandate dimensions may additionally carry controlled support categories. The routing
configuration maps each category to narrow thematic sections only when the dimension is marked
`should_shape_cv` and has `DIRECT` or `ADJACENT` Document A evidence. Free-text dimension IDs never
route Document B, and support categories cannot authorise another lane's summary, experience
framing or positioning playbook.

The assessment request is assembled as an exact reusable prefix followed by variable job content.
Stable assessment instructions, the canonical structured-output schema and the complete active
Document A file precede job metadata and the full job description. Traceability records the
Document A hash/version, prompt hash/version, schema version/hash, routing-set identity and requested
model, together with the configured reasoning effort. The privacy-safe cache identity is derived
from the stable input identifiers and hashes; it never contains prompt text, document content, job
content or model output. Reasoning effort is explicit request metadata but does not alter the
reusable input prefix.

### Generation stage 1 — select Document B content and create the CV brief

The selected lane is an exact key in a versioned SQLite routing set bound to the active Document B
version. The routing set is a configuration lookup, not fuzzy matching, heading similarity or model
interpretation. It selects the mandatory and optional section trees, including summary and
experience framing, bullet-library themes, skills guidance, anti-overclaiming rules, positioning
playbooks and the required output template. It may also declare excluded or cautious lanes.

The application retrieves the selected local section trees by their stable section IDs. It may then
run a scoped vector search only across the section IDs authorised by that routing set. The query is
built from the job description, Phase 1 evidence anchors, primary and secondary angles, strengths
to emphasise, and gaps or claims to avoid. Retrieval may suggest optional bullet candidates,
technical keywords and secondary themes; it cannot select the primary lane or replace mandatory
local sections.

Generation stage 1 returns a structured CV-generation brief containing the selected lane, primary narrative,
optional secondary angle, evidence to lead with, evidence to soften or exclude, selected Document B
section IDs, selected bullet or passage IDs, mandatory guardrail IDs, and proposed CV structure.

### Generation stage 2 — generate the first CV

Generation stage 2 receives the job description, assessment, retained stage-one brief, exact local
Document B sections selected by the brief, and any recorded vector-retrieved passages. It
generates and retains a structured first CV. The model does not independently search the complete
Document B.

### Generation stage 3 — review and rewrite

Generation stage 3 reviews the generated CV against the job description, assessment, stage-one brief,
and the same Document B sections and guardrails used for generation. It checks alignment, evidence
quality, length, overclaiming and writing quality before producing the final rewritten CV.

A new broad vector search is not normally performed during Phase 4. A targeted search is permitted
only when the review identifies a specific evidence or wording gap, and it remains limited to the
authorised section scope.

### Design principle

```text
Phase 1 recommends the lane
    ↓
The user confirms the lane
    ↓
The routing table selects authorised sections
    ↓
Scoped vector search finds optional material within that scope
    ↓
Phase 2 selects and the user approves the material
    ↓
Phase 3 generates the CV
    ↓
Phase 4 reviews and rewrites it
```

The primary lane always controls the headline, summary and dominant positioning. A controlled,
evidence-supported secondary CV angle may authorise only supporting bullet, skills and guardrail
material. Credible material mandate dimensions may also authorise configured thematic bullet
libraries without exposing a whole supporting lane. One dominant narrative therefore does not imply
one evidence category. The routing table provides control and reproducibility. Vector retrieval
provides flexibility and job-specific relevance within the authorised scope.

## English CV pipeline

```text
Assessment + JD + approved CV-generation brief + selected Document B material
→ English prompt 1
→ English prompt 2
→ English prompt 3
→ English prompt 4
→ Final structured CV
→ English DOCX renderer
```

Every stage receives explicit persisted input. No long-lived conversation state is assumed.

## French CV pipeline

```text
Complete English pipeline
→ French prompt 1
→ French prompt 2
→ Factual consistency validation
→ French DOCX renderer
```

French references guide wording and conventions only. They cannot strengthen evidence.

## Structured outputs

Assessment and final CV outputs use explicit schemas and Pydantic validation.

The final CV structure returned by stage 3 includes:

- positioning title and profile;
- skills entries;
- ordered experience blocks for the template contract's declared experience targets, with optional
  title, introduction and bullets.

The model returns semantic content only. The local template contract deterministically binds each
returned value to its configured DOCX placeholder, so the model never selects, repeats or omits a
template placeholder.

Education, contact details, languages, employer headings and other static content remain owned by the
user-managed DOCX template rather than generated output.

## Failure handling

- Bounded retry for transient OpenAI or schema failures.
- Preserve prior successful pipeline stages.
- Restart from a failed stage where safe.
- Full regeneration remains available.
- Prior usable generated DOCX remains until replacement succeeds.

## Usage tracking

For every model call store:

- operation;
- pipeline stage;
- model;
- input tokens;
- cached input tokens where returned;
- cache-write tokens where returned;
- output tokens;
- reasoning tokens where returned;
- total tokens;
- duration;
- response ID;
- success or error;
- prompt and reference versions.

Every actual token-bearing Responses API invocation is recorded, including calls that return a
provider response but later fail local structured-output validation. File upload, vector-store
polling, deletion and retrieval are not LLM calls and are outside this token-usage table.

Provider-reported token categories remain nullable: `NULL` means unreported and zero means reported
as zero. Failed calls retain whatever response ID, request ID, status, usage and safe failure
metadata are available without storing provider error bodies.

Cache economics use a versioned SHA-256 identity derived only from canonical operation, pipeline
stage, requested model and prompt/reference version identifiers or hashes. The identity permits
cache-write cost to be compared with later cached-input savings without persisting the raw cache
key, prompt text, Document A/B content, job description or model output.
