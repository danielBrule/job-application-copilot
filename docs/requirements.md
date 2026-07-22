# Requirements

## 1. Purpose

Build a local application that reduces repetitive work in job assessment, selective CV generation and application tracking while preserving human judgement and factual accuracy.

## 2. Stable reference inputs

The Settings screen manages:

- Document A — Career Strategy, Evidence & Job Assessment Guide
- Document B — CV Generation & Positioning Guide
- Assessment prompt
- Four ordered English CV-generation prompts
- Two additional French prompts
- English CV template
- French CV template
- One or more previous French CVs used only as style and terminology references

All maintained documents and templates use DOCX. Updates are expected to be rare but must be supported through simple version replacement.

## 3. Job entry

Required fields:

- Company
- Job title
- Location: `UK`, `FR`, `CH`
- Language: `EN`, `FR`
- Full job description

Optional fields:

- Source, default `LinkedIn`; examples include company website, headhunter on LinkedIn and other
- Job URL
- Notes
- Date added, defaulting to the current date but editable

A saved job can be edited without automatically launching or relaunching assessment.

## 4. Assessment

The user selects one or more rows and clicks **Assess selected jobs**.

Requirements:

- Processing runs outside the Streamlit request and may take a long time.
- Sequential processing is the default.
- A configuration parameter may allow bounded parallelism.
- Each job is processed independently.
- A failure does not stop the rest of the batch.
- Completed or failed jobs can be manually reassessed, including multiple selected rows in one action.
- A previous valid assessment remains available until a replacement completes successfully.
- Editing company, title, location, language or JD marks the assessment stale.
- Editing URL, source or notes does not mark it stale.

Stored assessment output:

- Short summary
- Primary and optional secondary role family
- Go / Caution / Stretch / No-Go recommendation
- Fit score
- Interview probability range and confidence
- Strong fit signals
- Red flags and sustainability risks
- Recommended CV lane
- Evidence anchors and confidence
- Evidence gaps
- Overclaiming constraints
- Document A and prompt versions
- Model and usage metadata

The complete active Document A is authorised for assessment. Document B must not be supplied to assessment.

## 5. Human review

The user can record a decision independent of the model:

- Undecided
- Pursue
- Do not pursue

The model recommendation remains visible.

The user can confirm or change the recommended CV lane before generation.

## 6. CV selection and generation

A pursued job may be marked **Selected for CV generation**.

The user can select one or more eligible rows and click **Generate selected CVs**.

English path:

1. English prompt 1
2. English prompt 2
3. English prompt 3
4. English prompt 4
5. English DOCX rendering

French path:

1. English prompt 1
2. English prompt 2
3. English prompt 3
4. English prompt 4
5. French prompt 1
6. French prompt 2
7. French DOCX rendering

Requirements:

- The stored assessment is input to CV generation.
- Document B is routed by the selected lane.
- Mandatory B sections are selected deterministically.
- Semantic retrieval may add relevant context but must not replace mandatory sections.
- One failed CV must not stop other jobs.
- CV generation and regeneration can be launched for multiple selected rows.
- The prior usable generated file remains until regeneration succeeds.
- Generated content is structured before DOCX rendering.
- The model does not control Word formatting directly.

## 7. Generated files

All generated CVs are saved in one configurable folder.

Filename:

```text
resume - Daniel Brule - <YYYY-MM-DD> - <Company>.docx
```

Rules:

- Date is generation date.
- Company is sanitised for Windows.
- A numeric suffix prevents accidental overwrite.
- No Word-document version history is required.

## 8. Existing CV upload

For a job, the user may skip generation and upload an existing DOCX.

The application:

- validates the DOCX;
- copies it into the local uploaded-CV folder;
- associates it with the job;
- records source `UPLOADED`;
- sets status `READY_FOR_REVIEW`.

The uploaded CV is not parsed or automatically rewritten.

## 9. Review and approval

The active CV can be opened:

- from the Jobs dashboard;
- from the Job Details CV tab.

The local Windows default DOCX application, normally Microsoft Word, is used.

The user edits the file in Word and explicitly clicks **Approve CV** in the application. Approval stores its date. No in-app Word editor or Word version history is required.

## 10. Application tracking

Application status is free text because companies use different processes.

A job stores:

- Application status
- Application date
- Next action
- Next-action date
- Salary expectation
- General notes
- Closure or rejection reason

Work-authorisation tracking is excluded.

A job can have multiple contacts. Each contact contains:

- Name
- Title
- LinkedIn URL
- Interview date
- Notes

## 11. Background operations

The application displays assessment and CV-generation tasks with:

- Job
- Batch
- Operation
- Status
- Start and completion times
- Error
- Retry action

Interrupted tasks become retryable after worker restart.

## 12. KPI dashboard

Simple cards appear above the Jobs table:

- Jobs entered
- Jobs assessed
- CVs generated
- CVs uploaded
- CVs approved
- Total and average assessment tokens
- Total and average CV-generation tokens
- Total and average assessment processing time
- Total and average CV-generation processing time
- Failed tasks requiring attention

Generated and uploaded CVs are counted separately. Average usage/time is calculated using successfully completed jobs.

## 13. Reference replacement

When a new A or B version is uploaded:

1. validate and save it locally;
2. calculate a hash;
3. assign a version;
4. upload/index where required;
5. validate processing;
6. activate the new version only after success;
7. mark the previous version inactive.

Old remote vector stores do not need immediate deletion. The MVP provides a manual cleanup action. Local DOCX files and metadata remain available.

## 14. Non-functional requirements

- Local Windows execution
- Local SQLite database
- Streamlit UI
- OpenAI model provider
- DOCX source documents and templates
- Long-running work outside Streamlit request execution
- Sequential default with configurable bounded concurrency
- Failures isolated by job
- Private data excluded from Git
- Clear model/document/prompt/template version traceability
- No automatic application submission
- No browser automation
- No mass outreach
- No multi-user support in the MVP
