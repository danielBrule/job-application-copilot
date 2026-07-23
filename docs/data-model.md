# Data model

## Relationships

```text
Job 1 ── 0..1 Current Assessment
Job 1 ── 0..1 Active CV
Job 1 ── 0..* Contacts
Job 1 ── 0..* Background Tasks
Job 1 ── 0..* LLM Calls
Background Batch 1 ── 1..* Background Tasks
Reference Asset Type 1 ── 0..* Versions
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
- `user_decision`: Undecided / Pursue / Do not pursue
- `application_status`, free text
- `application_date`
- `next_action`
- `next_action_date`
- `salary_expectation`
- `closure_reason`
- `created_at`
- `updated_at`

## Assessment

One current record per job.

Key fields:

- `job_id`
- `status`: pending / running / assessed / failed
- `summary`
- `primary_role_family`
- `secondary_role_family`
- `decision`: Go / Caution / Stretch / No-Go
- `decision_reason`
- `fit_score`
- `interview_probability_low`
- `interview_probability_high`
- `interview_probability_confidence`
- `strong_fit_signals`
- `risks`
- `evidence_anchors`
- `evidence_confidence`
- `evidence_gaps`
- `recommended_cv_lane`
- `selected_cv_lane`
- `secondary_cv_angle`
- `overclaiming_constraints`
- `assessment_notes`
- `document_a_version`
- `prompt_version`
- `model_name`
- `assessed_at`
- `source_job_updated_at`
- `error_message`

A failed reassessment must not delete the last valid result.

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

## LLM call

- `job_id`
- `task_id`
- `operation`
- `pipeline_step`
- `model_name`
- `input_tokens`
- `cached_input_tokens`
- `output_tokens`
- `total_tokens`
- `started_at`
- `completed_at`
- `duration_seconds`
- `status`
- `response_id`
- prompt/document version metadata

This table is the source for token and processing-time KPIs.

## Reference asset

- `asset_type`
- `name`
- `version`
- `file_path`
- `file_hash`
- `is_active`
- `processing_status`
- `openai_file_id`
- `openai_vector_store_id`
- `uploaded_at`

Asset categories:

- Document A
- Document B
- Assessment prompt
- Four English CV prompts
- Two French prompts
- English template
- French template
- French reference CV

Multiple French reference CVs may be active. Single-instance asset types have one active version.

## Document B section

Locally extracted for deterministic routing:

- `document_b_version`
- `section_id`
- `heading_number`
- `heading_title`
- `heading_level`
- `sequence`
- `section_text`

## Application settings

- database path
- shared CV folder for generated and uploaded CVs
- logs folder
- assessment worker count, default 1
- CV worker count, default 1
- default source, LinkedIn
- default location, UK
- default language, EN
