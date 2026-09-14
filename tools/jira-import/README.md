# Jira import / migration scripts

One-off data-migration tools used to import an existing Jira project (Lokko) into this Plane
instance. Not part of the running application — run manually against a deployed instance.

- `import_jira.py` — main Jira → Plane issue import.
- `import_jira_attachments.py` — imports/backfills Jira attachments onto already-migrated issues.
- `backfill_assignees.py` — one-off backfill for assignee mapping issues found after the initial import.
- `backfill_attachment_embeds.py` — one-off backfill for inline attachment embeds in issue descriptions.
- `config-jira-ingestor.json` — Jira source connection/config for the above scripts.
- `requirements-ingestor.txt` — Python dependencies for running these scripts (separate from the
  main API's dependencies).

Run artifacts (progress files, logs, the original CSV export) are kept alongside the deployment,
not under source control here.
