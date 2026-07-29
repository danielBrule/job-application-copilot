# Screen specification

## Navigation

- Jobs
- Background Runs
- Settings

Job Details opens from the Jobs table.

## 1. Jobs dashboard

### KPI cards

- Jobs entered
- Jobs assessed
- CVs generated
- CVs uploaded
- CVs approved
- Assessment tokens: total / average
- CV-generation tokens: total / average
- Assessment time: total / average
- CV-generation time: total / average
- Failed tasks requiring attention

### Filters

- Text search across company and title
- Location
- Language
- Source
- Assessment status
- Model decision
- User decision
- CV status
- Application status

### Table columns

- Select
- Company
- Job title
- Location
- Language
- Source
- Date added
- Assessment status
- Assessment stale
- Model decision
- Fit score
- Interview probability
- User decision
- Selected CV lane
- CV status
- CV source
- Open CV
- Application status
- Next action
- Next-action date
- Updated

### Batch actions

- Assess selected
- Reassess selected stale jobs
- Select for CV generation
- Generate selected CVs
- Regenerate selected CVs
- Delete selected jobs, with confirmation

The Open CV action is available directly in the table when a valid file exists.

## 2. Add / edit job

Fields:

- Company
- Job title
- Location: UK / FR / CH
- Language: EN / FR
- Source, default LinkedIn
- Job URL
- Full JD
- Date added, auto-filled with current date and editable
- Notes
- Relevance override: Use assessment relevance / High / Medium / Low

Actions:

- Save
- Save and add another
- Cancel

Editing never launches assessment automatically. Relevant edits may create a stale-assessment warning.

## 3. Job Details

### Tab A — Job

- View and edit all job fields
- Full JD
- URL
- Notes
- Assess / Reassess when stale
- Delete, with confirmation

### Tab B — Assessment

Display:

- Summary
- Role family
- Recommendation
- Model relevance and effective relevance
- Fit score
- Interview probability
- Strong signals
- Risks
- Evidence anchors
- Evidence gaps
- Recommended CV lane
- Overclaiming constraints
- Document and prompt versions
- Stale indicator

Editable user controls:

- User decision: Undecided / Pursue / Do not pursue
- Relevance override: Use assessment relevance / High / Medium / Low
- Selected CV lane
- Assessment notes
- Select for CV generation

The model recommendation is never overwritten by the user decision.

### Tab C — CV

When no CV exists:

- Generate CV
- Upload existing DOCX

During generation:

- Status
- Current pipeline stage
- Error where relevant
- Regenerate

When a CV exists:

- Filename and local path
- Source: Generated / Uploaded
- Open CV
- Approve CV
- Optional review notes
- Approval date

No in-application document editor and no Word version history.

### Tab D — Application

Fields:

- Free-text application status
- Application date
- Next action
- Next-action date
- Salary expectation
- Notes
- Closure reason

Contacts table:

- Name
- Title
- LinkedIn URL
- Interview date
- Notes
- Add / edit / delete

## 4. Background Runs

Columns:

- Batch
- Job
- Operation
- Status
- Started
- Completed
- Duration
- Error
- Retry

Filters:

- Operation
- Status
- Batch
- Job

A failure affects only its own task.

The batch filter identifies batches by ID and launch time. Each task exposes retained execution
attempts so errors and timings from earlier retries remain reviewable. Displayed pending or running
results refresh every 60 seconds, and an explicit refresh action is always available.

## 5. Settings

### Reference asset overview

The top of the page shows every input required by the assessment and CV-generation
pipelines, including missing inputs:

- Document A
- Document B
- English CV template
- French CV template
- French CV examples, measured against the configured active-ready minimum
- Every enabled prompt group, using its current data-driven required count

For stored assets, the overview shows the asset key, name, immutable stored filename,
version, upload time, processing status and active state. The active version and a newer
pending or failed candidate appear separately so a failed replacement does not make the
currently usable input appear unavailable. French examples are not limited to a fixed
number or fixed set of keys.

Below the overview, working DOCX upload/replacement forms are provided for the four canonical
document/template assets. A dynamic French-example form accepts only a meaningful name and DOCX;
the application derives its internal stable key. Reusing the same normalized name with changed
content creates the next version, while duplicate content is rejected across all example names.
Prompts retain their separate text editing workflow.

French-example readiness is displayed once above the asset table. Each active example then
appears in exactly one table row. Removing an example excludes it from readiness and hides it
from the active table without deleting its retained versions or files. Removed examples remain
available through a Restore action.

After local validation, templates and French examples become active and `READY`. Documents A
and B remain inactive until their OpenAI processing succeeds. The prior active document remains
visible and usable. Invalid or duplicate uploads do not alter the active version.

The Document A and Document B forms use **Upload and activate with OpenAI** for their first
version and **Replace and activate with OpenAI** afterward. Document A validates and stores the
complete DOCX, uploads it and activates it in that single workflow. Document B additionally waits
for vector-store indexing and validates retrieval before refreshing the overview after activation.
When the latest Document B remains pending, processing or failed, Settings additionally shows
**Process and activate** as a recovery action. While processing, the page shows a spinner. A safe
actionable error is shown on failure and the prior active version remains in use. After an
application restart, `PROCESSING` candidates remain eligible for recovery and resume from the
last OpenAI identifier saved locally.

### Assessment

- Active Document A DOCX
- Assessment prompt
- Prompt text editor and retained versions
- Versions and processing state
- Replace/edit actions

### CV generation

- Active Document B DOCX
- Four ordered English prompts
- Add, enable or disable prompt definitions
- Versions and processing state
- Replace/edit actions

### French

- French DOCX template
- Previous French CV examples
- French prompt 1
- French prompt 2

The two French prompts are shown after the four English prompts in the pipeline order.
These are the initial enabled definitions. Prompt counts, pipeline groups and languages are
data-driven. The Settings screen shows ready/required counts and missing prompt keys for each
group.

### Templates and storage

- English CV template
- French CV template
- Shared CV folder for generated and uploaded CVs

### Processing

- Assessment worker count, default 1
- CV worker count, default 1

### Remote assets

- Active OpenAI identifiers
- Inactive tracked vector stores and uploaded files
- Stored vector-store usage where available
- Per-version confirmation and manual delete action
- Local DOCX and version metadata retained after remote cleanup
- Restore-and-activate action for retained Document A and Document B versions with no remote IDs
