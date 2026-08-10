# Data model

## Relationships

```text
Job 1 ── 0..1 Current Assessment
Job 1 ── 0..1 Active CV
Job 1 ── 0..* Contacts
Job 1 ── 0..* Background Tasks
Job 1 ── 0..* LLM Calls
Background Batch 1 ── 1..* Background Tasks
Background Task 1 ── 0..* Execution Attempts
Background Task 1 ── 0..* LLM Calls
Execution Attempt 1 ── 0..* LLM Calls
Reference Asset Type 1 ── 0..* Versions
Prompt Definition 1 ── 0..* Prompt Reference-Asset Versions
Document B Version 1 ── 0..* Lane Routing Sets
Lane Routing Set 1 ── 1..* Lane Routes
CV Generation 1 ── 1 Structured CV-generation Brief
```

## Job

Key fields:

- `id`
- `company`
- `job_title`
- `location`: UK / FR / CH
- `language`: EN / FR
- `source`, default LinkedIn
- `job_url`
- `job_description`
- `date_added`, current date by default and editable
- `general_notes`
- `relevance_override`: optional High / Medium / Low human override
- `user_decision`: Undecided / Pursue / Do not pursue
- `application_status`, free text
- `application_date`
- `next_action`
- `next_action_date`
- `salary_expectation`
- `closure_reason`
- `created_at`
- `updated_at`
- `assessment_input_updated_at`: changes only when company, title, location, language or job
  description changes

## Assessment

One current record per job.

Key fields:

- `job_id`
- `status`: pending / running / assessed / failed
- `model_relevance`: High / Medium / Low
- `role_snapshot`
- `real_mandate`
- `primary_role_family`: configured lane identifier
- `secondary_role_family`: optional configured lane identifier
- `seniority_fit`: 0 to 10
- `technical_bar`
- `tech_bar_fit`: 0 to 10
- `decision`: Go / Caution / Stretch / No-Go
- `decision_reason`
- `fit_score`: 0 to 10
- `priority_score`: 0 to 10
- `interview_probability_low`: 0 to 10
- `interview_probability_high`: 0 to 10
- `interview_probability_confidence`: 0 to 10
- `strong_fit_signals`
- `red_flags`
- `sustainability_risks`
- `evidence_gaps`
- `evidence_anchors`
- `material_mandate_dimensions`: compact requirement, importance, Document A evidence strength,
  evidence-anchor references and CV-relevance handoff
- `evidence_confidence`: one overall 0-to-10 score
- `recommended_document_b_lane`: configured lane identifier
- `selected_cv_lane`: configured lane identifier
- `secondary_cv_angle`
- `overclaiming_risks`
- `assessment_notes`
- `document_a_version`
- `prompt_version`
- `model_name`
- `assessed_at`
- `source_job_updated_at`
- `error_message`

A failed initial assessment is retained and retryable. A successful assessment can be reassessed
only after a relevant job edit makes it stale. The successful row remains available while that
reassessment runs, and a failed reassessment must not replace it; operational retry and failure
details remain on the background task and its retained attempts.

Staleness compares `Assessment.source_job_updated_at` with
`Job.assessment_input_updated_at`. Administrative, application-tracking and human-review edits do
not advance the job timestamp and therefore do not make an assessment stale.

An `ASSESSED` row must populate the model relevance, role snapshot, real mandate, primary and
secondary role families, fit and priority scores, strong-fit signals, red flags, sustainability
risks, technical bar, seniority fit, evidence anchors, evidence gaps, overclaiming risks, decision,
decision reason and recommended Document B lane. Collection fields are stored as non-null JSON
arrays and may be empty when the assessment explicitly finds no items.

Effective relevance is `Job.relevance_override` when present, otherwise the current
`Assessment.model_relevance`. Keeping both values preserves the model output when the user
overrides it.

Role-family identifiers and CV-lane identifiers share one installation-specific vocabulary. The
current validated Document B routing set defines the allowed values; they are stored as strings
rather than a global database or Python enum.

## CV

One active CV per job.

Key fields:

- `job_id`
- `source`: GENERATED / UPLOADED
- `status`: selected / pending / generating / ready_for_review / failed / approved
- `language`: EN / FR
- `file_name`
- `file_path`
- `selected_cv_lane`
- `document_a_version`
- `document_b_version`
- `template_version`
- `generation_prompt_versions`
- `french_prompt_versions`
- `review_notes`
- `generated_or_uploaded_at`
- `approved_at`
- `error_message`

No Word-document version history is required.

## CV-generation brief

One stage-one handover is retained for each generated CV task. It records:

- confirmed selected lane and optional secondary angle
- primary narrative
- evidence to lead with, soften or exclude, always anchored to Document A
- selected Document B local section IDs
- selected optional bullet or vector-passage IDs
- mandatory guardrail IDs
- proposed CV structure
- Document B, routing-set and prompt versions

Generation stages 2 and 3 use this retained brief and its selections. A later broad Document B search is
not an implicit input to either phase.

## CV-generation draft

One structured stage-two draft is retained for each generated CV task. It records the complete tailored
English CV draft plus the evidence deliberately prioritised, softened or excluded. Stage 3 uses this
retained draft together with the retained brief and the same authorised Document B material.

## Final structured CV

The final CV is structured generated content for a user-managed DOCX template. Every generated text,
experience block and skills block records its bracketed template placeholder. Template-owned contact
details, education, languages, static employer headings and static roles remain outside model output.

## Contact

Multiple records per job.

- `job_id`
- `name`
- `title`
- `linkedin_url`
- `interview_date`
- `notes`
- timestamps

## Background batch

- `id`
- `operation`
- `created_at`
- optional summary metadata

## Background task

- `batch_id`
- `job_id`
- `operation`: assessment / CV generation
- `status`: pending / running / completed / failed / interrupted
- `pipeline_step`
- `started_at`
- `completed_at`
- `retry_count`
- `error_message`
- payload metadata

A background task is the logical job-specific unit in a batch. Retrying it returns that same
task to `PENDING`; it does not create a duplicate logical task or alter completed siblings.

## Background task attempt

- `task_id`
- `attempt_number`
- `status`: running / completed / failed / interrupted
- `pipeline_step`
- `started_at`
- `completed_at`
- `error_message`

An attempt is created when the worker claims a pending task. Its terminal state is retained when
the logical task is retried, providing an audit trail of earlier errors and timings.

## LLM call

- `job_id`
- nullable `task_id`
- nullable `task_attempt_id`; when present, `task_id` is also required and must own the attempt
- `operation`
- `pipeline_step`
- `call_sequence`
- `provider`
- `requested_model`
- nullable `resolved_model`
- `input_tokens`
- `cached_input_tokens`
- `cache_write_tokens`
- `output_tokens`
- `reasoning_tokens`
- `total_tokens`
- `started_at`
- `completed_at`
- `duration_seconds`
- `status`
- nullable `response_id` and provider request ID
- nullable HTTP status, service tier and controlled incomplete reason
- retry number and controlled failure category
- cache identity hash, identity-recipe version and retention setting
- prompt/document version metadata containing identifiers, versions and hashes only

`job_id` is required. The optional task and attempt associations identify the logical background
operation and exact worker execution attempt that incurred the call. When associated, the job and
operation must agree across the call, task and attempt.

Provider-reported token fields are nullable. `NULL` means that the provider did not report the
category, while `0` means that it explicitly reported zero. `cached_input_tokens` maps the
provider's `cached_tokens` field. Cache-read and cache-write counts are accounting details and are
not added again to `total_tokens`.

The cache identity is a SHA-256 hash derived only from canonical non-sensitive identifiers such as
operation, pipeline step, requested model, prompt version and applicable Document A, Document B,
template or reference versions. Its version records the hash recipe. Raw prompts, cache keys,
Documents A/B, job descriptions, model output and provider error bodies are not stored here.

Successful and failed calls with reported usage both contribute to usage totals. Counts remain
separated by outcome, and calls where usage was unavailable remain distinguishable from calls that
reported zero. This table is the source for later token, cache-economics and processing-time KPIs.

## Reference asset

- `asset_key`: stable logical identity shared by all versions of one asset
- `asset_type`
- `name`
- optional lowercase `language_code`, such as `en`, `fr` or `de`
- `version`
- `file_path`
- `file_hash`
- `is_active`
- `processing_status`
- `processing_error`, the latest sanitised failure or null
- `openai_file_id`
- `openai_vector_store_id`
- `openai_vector_store_usage_bytes`, the processed remote storage size where applicable
- `uploaded_at`
- `updated_at`

Asset types are deliberately broad:

- document
- prompt
- template
- reference example

The asset key identifies Document A, Document B, each prompt, each language-specific template
and each reference example without hard-coding a fixed number of prompts or languages into the
schema. Only one version of an asset key may be active. Multiple reference examples may be active
because each example has its own key.

Processing status is `PENDING`, `PROCESSING`, `READY` or `FAILED`. Only a `READY` version may be
active. Prior valid versions remain `READY` when made inactive. Starting or successfully
completing remote processing clears `processing_error`; a failed attempt records its latest
actionable, secret-safe explanation.

For Document B, the vector-store ID is recorded as soon as the remote store is created.
Activation requires the attached file to reach OpenAI status `completed` and a direct validation
search to return non-empty content from that file. The processed usage bytes are retained for
inactive stores so later cleanup can show their storage impact. Indexing does not report model
token usage. Explicit cleanup clears successfully deleted remote identifiers and vector-store
usage from an inactive version while retaining its local path, hash, version, status and dates.
Each remote association is cleared after its corresponding deletion so partial cleanup can be
retried safely. Restoring a cleaned version reuses that same row and local file, verifies the
stored hash, and repopulates its remote identifiers rather than creating another version.

## Prompt definition

One row describes the stable pipeline role shared by every text version of a prompt:

- `asset_key`, the primary key and logical link to reference-asset versions
- `name`
- `pipeline_group`, an enum-free safe path such as `assessment` or `generation/english`
- optional lowercase `language_code`
- positive `position`, unique within the pipeline group
- `is_enabled`
- timestamps

An enabled definition is required even before prompt text exists. It is ready only when its
asset key has an active `READY` prompt reference-asset version. Disabled definitions and all
their immutable text versions are retained but do not count as required. Prompt counts,
pipeline groups and language codes are therefore data-driven rather than schema constants.

## Document B section

Locally extracted for deterministic routing:

- `reference_asset_id`, linking the exact Document B version
- `section_id`
- `heading_number`
- `heading_title`
- `heading_level`
- `sequence`
- `section_text`

The document preamble is retained as level `0`. Heading sections use positive Word heading
levels. Section IDs are deterministic within a version: an explicit heading number is preferred,
otherwise the normalized hierarchy of heading titles is used. Sequence and section ID are each
unique within one Document B version.

## Document B lane routing set

Versioned SQLite configuration validated against one exact Document B reference-asset version:

- routing-set identity, version, status and timestamps
- `document_b_reference_asset_id`
- controlled lane identifier
- route entries containing `section_id`, role, mandatory or optional inclusion, descendant handling
  and sequence
- excluded or cautious lane/section declarations where applicable

Only a validated active routing set may be used with its bound active Document B version. Validation
requires every referenced local section ID to exist in that version.

## Document B retrieval record

Section-derived vector-index records and Phase 2 selections retain:

- exact Document B version and local `section_id`
- remote vector record identifier and content hash where applicable
- retrieval query/result provenance without logging unnecessary private prompt content
- selected or rejected status in the CV-generation brief

Every vector query applies the section IDs authorised by the active routing set. Vector results are
supplementary material, not a substitute for the local mandatory section tree.

The local retrieval trace records the private query text, routing-set identity and configuration
version, followed by the returned passage IDs, scores, verified source-record IDs and metadata.
It is retained for reproducibility, not application logging.

## Application settings

- database path
- shared CV folder for generated and uploaded CVs
- logs folder
- assessment worker count, default 1
- CV worker count, default 1
- default source, LinkedIn
- default location, UK
- default language, EN
- minimum active `READY` French reference examples, default 2
