# Local operations

This guide contains the setup and operational detail kept out of the portfolio-focused root
[README](../README.md). Job descriptions, career documents, generated CVs, databases and logs are
private local data; do not commit or publish them.

## Setup and configuration

### Prerequisites

- Python 3.12 or later
- Poetry 2.x
- Microsoft Word for manual DOCX editing

If the current PowerShell session blocks local scripts, allow them only for that session:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

Create or update the environment, then optionally activate it:

```powershell
.\dev.ps1 env
. .\dev.ps1 activate
```

Configuration uses process environment variables and an optional `.env` file in the directory
where the application starts. Copy `.env.example` to `.env` for local overrides. Keep it private.

| Variable | Default |
| --- | --- |
| `JAC_DATA_DIR` | `data` |
| `JAC_DATABASE_PATH` | `<JAC_DATA_DIR>/database/job_application_copilot.db` |
| `JAC_CV_FOLDER` | `<JAC_DATA_DIR>/cvs` |
| `JAC_LOGS_FOLDER` | `<JAC_DATA_DIR>/logs` |
| `JAC_REFERENCE_FOLDER` | `<JAC_DATA_DIR>/reference` |
| `JAC_ASSESSMENT_MODEL` | `gpt-5.6-sol` |
| `JAC_ASSESSMENT_REASONING_EFFORT` | `medium` |
| `JAC_ASSESSMENT_MAX_RETRIES` | `2` |
| `JAC_ASSESSMENT_RETRY_BASE_DELAY_SECONDS` | `1` |
| `JAC_ASSESSMENT_WORKER_COUNT` | `1` |
| `JAC_CV_WORKER_COUNT` | `1` |
| `JAC_LOG_LEVEL` | `INFO` |
| `JAC_LOG_MAX_SIZE_MB` | `5` |
| `JAC_LOG_BACKUP_COUNT` | `5` |
| `JAC_OPENAI_VECTOR_STORE_TIMEOUT_SECONDS` | `300` |
| `JAC_MINIMUM_FRENCH_REFERENCE_EXAMPLES` | `2` |
| `JAC_DEFAULT_SOURCE` | `LinkedIn` |
| `JAC_DEFAULT_LOCATION` | `UK` |
| `JAC_DEFAULT_LANGUAGE` | `EN` |
| `OPENAI_API_KEY` | unset |

Supported locations are `UK`, `FR` and `CH`; supported languages are `EN` and `FR`. Relative paths
resolve from the application's working directory. Use `JAC_DATA_DIR` to move all private data
together; the individual path settings are optional overrides.

## Local data, references and database

Create missing private directories and validate paths:

```powershell
.\dev.ps1 directories
```

Create or upgrade the SQLite database, or preview migrations as SQL:

```powershell
.\dev.ps1 database
.\dev.ps1 database-sql
```

The database uses Alembic migrations, WAL mode, foreign keys and a five-second busy timeout. Do
not commit the database file.

Reference assets, prompts, templates and generated CVs remain below the configured private data
directory. The application versions assets immutably and validates DOCX packages before retaining
them. Read [architecture](architecture.md#5-document-handling) and the
[OpenAI pipeline](openai-pipeline.md) before operating reference-asset activation or cleanup.

Inspect the local Document B routing manifest without changing data or making model calls:

```powershell
.\dev.ps1 document-b-routing
.\dev.ps1 document-b-routing -DocumentBVersion 3
.\dev.ps1 document-b-routing -DocumentBVersion 3 -Lane HEAD_OF_SOLUTIONS_ARCHITECTURE
```

Each installation owns its editable routing file at
`data/reference/routing/document-b-lane-routes.yaml`, initially copied from
[`templates/document-b-lane-routes.template.yaml`](../templates/document-b-lane-routes.template.yaml).
See [Document B routing manifest](document-b-routing-manifest.md) before editing it.

For development only, reset all retained reference assets with explicit confirmation:

```powershell
.\dev.ps1 reset-reference-assets -Force
```

This removes tracked local reference files and their database rows, and removes tracked remote
OpenAI resources first where recorded. It preserves prompt definitions, jobs and unrelated private
data.

## Run and verify

Start the interactive UI:

```powershell
.\dev.ps1 ui
```

Run the normal checks:

```powershell
.\dev.ps1 test
.\dev.ps1 coverage
.\dev.ps1 lint
.\dev.ps1 type
```

| Target | Scope | External side effects | CI |
| --- | --- | --- | --- |
| `test` | Pytest suite except opt-in integrations | Temporary local files and SQLite databases | Yes |
| `coverage` | Test suite with branch coverage report | Temporary local files and SQLite databases | Yes |
| `lint` | Ruff lint and formatting checks | None | Yes |
| `type` | Mypy analysis of the production package | None | Yes |
| `test-openai` | Live file and vector-store integration tests | Billable remote resources, created then deleted | No |
| `ui` | Interactive Streamlit application | May write private data and call OpenAI after an explicit action | No |

Run `./dev.ps1 help` to list available commands. The real OpenAI tests are opt-in and should only
be run with an intended billable API account. See [security and privacy](../SECURITY.md) before
sharing diagnostic material.

## Troubleshooting

The developer-script tests use a unique writable folder below `.pytest-tmp`. When invoking pytest
directly in a restricted environment, provide an equivalent project-local directory:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-tmp/local
```

When invoking `dev.ps1` from another working directory, pass its absolute path; the script resolves
project commands and check paths from the repository location.

## GitHub issue import

The implementation backlog can be imported into GitHub Issues with GitHub CLI. GitHub Issues is the
operational source of truth; the CSV is an import source and compact overall view. See
[Roadmap and issue workflow](backlog.md) for prerequisites, dry runs and ticket-specific import.
