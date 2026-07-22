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
- Reassess selected
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
- Assess / Reassess
- Delete, with confirmation

### Tab B — Assessment

Display:

- Summary
- Role family
- Recommendation
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

## 5. Settings

### Assessment

- Active Document A DOCX
- Assessment prompt
- Versions and processing state
- Replace/edit actions

### CV generation

- Active Document B DOCX
- Four ordered English prompts
- Versions and processing state
- Replace/edit actions

### French

- French DOCX template
- Previous French CV examples
- French prompt 1
- French prompt 2

The two French prompts are shown after the four English prompts in the pipeline order.

### Templates and storage

- English CV template
- French CV template
- Generated-CV folder
- Uploaded-CV folder

### Processing

- Assessment worker count, default 1
- CV worker count, default 1

### Remote assets

- Active OpenAI identifiers
- Inactive stores
- Manual delete action for inactive stores
