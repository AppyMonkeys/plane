#!/usr/bin/env python3
"""One-off: wire up issue_assignees for already-imported issues, to correct a
case-sensitivity bug in import_jira.py's assignee lookup (fixed there for any
future/re-run, but doesn't retroactively touch rows already committed)."""
import csv
import datetime as dt
import uuid

import psycopg2

DB = dict(host="plane-db", port=5432, dbname="plane", user="plane", password="plane")
CSV_PATH = "Jira_Lokko_export_csv.csv"
WORKSPACE_SLUG = "lokko"
PROJECT_IDENTIFIER = "LOKKO"
EXTERNAL_SOURCE = "jira_csv_import"
KNOWN_USER_EMAILS = {"varun sharma": "varun.sharma@appymonkeys.com"}

with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
    reader = csv.reader(f)
    header = next(reader)
    idx = {}
    for i, h in enumerate(header):
        idx.setdefault(h, []).append(i)
    rows = list(reader)

key_pos = idx["Issue key"][0]
assignee_pos = idx["Assignee"][0]
wanted = {r[key_pos].strip(): r[assignee_pos].strip() for r in rows if r[assignee_pos].strip().lower() in KNOWN_USER_EMAILS}
print(f"{len(wanted)} tickets in CSV assigned to a known user")

conn = psycopg2.connect(**DB)
cur = conn.cursor()
cur.execute("SELECT id FROM workspaces WHERE slug=%s", (WORKSPACE_SLUG,))
workspace_id = cur.fetchone()[0]
cur.execute("SELECT id FROM projects WHERE workspace_id=%s AND identifier=%s", (workspace_id, PROJECT_IDENTIFIER))
project_id = cur.fetchone()[0]
cur.execute("SELECT id, email FROM users")
user_by_email = {email.lower(): uid for uid, email in cur.fetchall()}

now = dt.datetime.now(dt.timezone.utc)
fixed = 0
for key, name in wanted.items():
    email = KNOWN_USER_EMAILS[name.lower()]
    uid = user_by_email.get(email.lower())
    if not uid:
        continue
    cur.execute(
        "SELECT id FROM issues WHERE project_id=%s AND external_source=%s AND external_id=%s AND deleted_at IS NULL",
        (project_id, EXTERNAL_SOURCE, key),
    )
    row = cur.fetchone()
    if not row:
        print(f"  {key}: issue not found, skipping")
        continue
    issue_id = row[0]
    cur.execute(
        "SELECT 1 FROM issue_assignees WHERE issue_id=%s AND assignee_id=%s AND deleted_at IS NULL",
        (issue_id, str(uid)),
    )
    if cur.fetchone():
        continue
    cur.execute(
        """INSERT INTO issue_assignees (id, created_at, updated_at, assignee_id, issue_id,
               project_id, workspace_id) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (str(uuid.uuid4()), now, now, str(uid), str(issue_id), project_id, workspace_id),
    )
    fixed += 1

conn.commit()
print(f"backfilled {fixed} issue_assignees rows")
cur.close()
conn.close()
