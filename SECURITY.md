# Security and privacy

## Scope

Job Application Copilot is a local-first, single-user portfolio project. It processes highly
sensitive career material, including CVs, job descriptions and notes. Read the
[operating boundary](README.md#operating-boundary) before using it.

## Data handling

- Private application data is configured below `JAC_DATA_DIR` and is excluded from Git.
- Secrets are supplied through environment variables or an untracked `.env` file; API keys,
  tokens, passwords and authorisation headers must never be logged or committed.
- Generated CVs, uploaded career documents, the SQLite database and logs are private local data.
- Explicit OpenAI actions transmit the selected workflow inputs to OpenAI. Do not use the project
  with data you are not authorised to process through that provider.
- Logs can contain sensitive content and provider details. Review and redact them before sharing.

## Security boundaries and limitations

This repository does not operate a hosted service, offer a security-response SLA, or provide
managed backup, encryption-at-rest, identity management, tenant isolation or monitoring. Users are
responsible for securing their workstation, OpenAI account, local data directory and backups.

The application includes secret-redaction safeguards in logging, but these are a safety net—not a
reason to place secrets in prompts, documents, issue reports or screenshots.

## Reporting a vulnerability

Do not publish secrets, personal documents, access tokens or reproducible exploitation details in
a public issue. Contact the repository owner through the linked GitHub profile with a concise,
sanitised description and enough information to reproduce the problem safely. This portfolio
project makes no guaranteed response-time commitment.
