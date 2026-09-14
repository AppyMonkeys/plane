#!/usr/bin/env python3
"""
Import Jira CSV export (Jira_Lokko_export_csv.csv) into a self-hosted Plane
Postgres database, by writing directly to the `issues` and related tables.

Design notes (see conversation for full rationale):
  - Target workspace/project are looked up by slug/identifier, not hardcoded.
  - Every imported issue is tagged external_source='jira_csv_import' and
    external_id=<Jira issue key>, so re-running this script is idempotent
    (already-imported keys are skipped) and the import can be identified /
    rolled back later via that tag.
  - Jira statuses not covered by Plane's 6 default states (On Hold, In
    Review, Waived, Duplicate) are added as new custom states.
  - Jira "Issue Type" (Bug/Task/Story/Epic/Sub-task/Improvement) and Jira
    "Labels" both become Plane labels (this project has work-item-types
    disabled, so there is no better native home for issue type).
  - Jira "Parent key" becomes Plane's native parent_id (sub-issue nesting) -
    this reconstructs Epic/Story/Sub-task hierarchy.
  - Only the assignee "Varun Sharma" maps to a real Plane account
    (varun.sharma@appymonkeys.com); every other Jira assignee/reporter name
    has no matching Plane user, so it can't be set as a real FK. Those names
    are preserved as a metadata footer appended to the issue description
    instead of being silently dropped.
  - Comments are imported as issue_comments; author is resolved to a human
    name (via a Reporter/Assignee/Creator Id -> name map built from the CSV
    itself) and prefixed into the comment text, since there's no Plane user
    to attribute them to.
  - Attachments themselves aren't migrated here (the CSV only has links back
    into the old Jira instance's API, which needs Jira auth) - that's
    import_jira_attachments.py's job, run separately afterwards. Jira's raw
    wiki markup for each attachment (`!file|width=..,height=..!` for inline
    images, `[^file]` for plain links) is deliberately left as literal text
    in the description below rather than rendered, so that script can find
    the exact spot to splice the real embed into once it uploads the file.
    Attachments with no such inline markup (attached to the ticket but never
    referenced in its text) are listed in a "not migrated" footer note
    instead, so nothing is silently lost; that script removes them from the
    note once it appends them to the description.
  - Jira "Description" is Jira wiki markup, not HTML. This script does a
    minimal plain-text-safe conversion (HTML-escape + wrap paragraphs), not
    a full wiki-markup renderer, so things like Jira's `#`/`*` lists or
    {code} blocks show up as literal text rather than real lists/code.

Run inside a container attached to the plane-app_default docker network, see
the accompanying run instructions.
"""
import argparse
import csv
import datetime as dt
import html
import re
import sys
import uuid

import psycopg2
import psycopg2.extras

DB = dict(host="plane-db", port=5432, dbname="plane", user="plane", password="plane")

CSV_PATH = "Jira_Lokko_export_csv.csv"
WORKSPACE_SLUG = "lokko"
PROJECT_IDENTIFIER = "LOKKO"
EXTERNAL_SOURCE = "jira_csv_import"

# Known Jira display name -> Plane user email. Only names that exactly match
# (case-insensitive) an existing Plane account get wired up as a real
# assignee FK; everyone else is preserved as text only.
KNOWN_USER_EMAILS = {
    "varun sharma": "varun.sharma@appymonkeys.com",
}

# Jira Status -> Plane state name. Statuses not in this map fall back to
# "Backlog". States not already in Plane's default 6 are created below.
STATUS_TO_STATE = {
    "Done": "Done",
    "In Progress": "In Progress",
    "To Do": "Todo",
    "Reopened": "Todo",
    "Waived": "Waived",
    "On Hold": "On Hold",
    "In Review": "In Review",
    "Duplicate": "Duplicate",
}
NEW_STATES = [
    # name, color, group, sequence
    ("On Hold", "#A16207", "backlog", 18000),
    ("In Review", "#0EA5E9", "started", 38000),
    ("Waived", "#6B7280", "cancelled", 56000),
    ("Duplicate", "#DC2626", "cancelled", 57000),
]

# Jira Priority -> Plane priority. Plane has no "lowest" tier.
PRIORITY_MAP = {
    "Highest": "urgent",
    "High": "high",
    "Medium": "medium",
    "Low": "low",
    "Lowest": "low",
    "": "none",
}

LABEL_COLORS = [
    "#3F76FF", "#F59E0B", "#46A758", "#DC2626", "#8B5CF6", "#0EA5E9",
    "#EC4899", "#84CC16", "#F97316", "#14B8A6", "#EAB308", "#A855F7",
]


def parse_jira_dt(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return dt.datetime.strptime(s, "%d/%b/%y %I:%M %p").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def html_escape_paragraphs(text):
    """Minimal, safe text->HTML: escape then wrap each non-empty line in <p>."""
    text = text or ""
    lines = [html.escape(line) for line in text.splitlines()] or [""]
    body = "".join(f"<p>{line}</p>" for line in lines if line.strip()) or "<p></p>"
    return body


def load_csv_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {}
        for i, h in enumerate(header):
            idx.setdefault(h, []).append(i)
        rows = [r for r in reader]
    return idx, rows


def col(idx, row, name, occurrence=0):
    positions = idx.get(name)
    if not positions or occurrence >= len(positions):
        return ""
    return row[positions[occurrence]].strip()


def multi_col(idx, row, name):
    return [row[p].strip() for p in idx.get(name, []) if row[p].strip()]


def build_account_id_name_map(idx, rows):
    m = {}
    for name_col, id_col in [("Reporter", "Reporter Id"), ("Assignee", "Assignee Id"), ("Creator", "Creator Id")]:
        for r in rows:
            name, accid = col(idx, r, name_col), col(idx, r, id_col)
            if name and accid:
                m[accid] = name
    return m


def parse_comment(raw, id_name_map):
    parts = raw.split(";", 2)
    if len(parts) < 3:
        return None
    date_s, accid, text = parts
    author = id_name_map.get(accid.strip(), accid.strip())
    return parse_jira_dt(date_s), author, text


def parse_attachment_name(raw):
    # Format is "date;accountId;filename;url", but the filename itself can
    # contain a literal semicolon (seen in practice: "lava; (2).mp4") - the
    # url is always the last field and always starts with http(s) and never
    # contains a semicolon, so anchor on that instead of assuming exactly 4
    # plain-split fields (see the identical fix in
    # import_jira_attachments.py's load_attachment_tasks).
    m = re.search(r";(https?://\S+)$", raw)
    prefix = raw[: m.start()] if m else raw
    parts = prefix.split(";", 2)
    return parts[2].strip() if len(parts) >= 3 else raw


def attachment_markup_pattern(filename):
    """Matches Jira's inline image-embed markup `!file|width=..,height=..!`
    or file-link markup `[^file]` / `[alias^file]` referencing this exact
    filename. Kept identical to the same helper in
    import_jira_attachments.py, which relies on this markup surviving into
    description_html untouched to know where to embed the real attachment
    later."""
    esc = re.escape(filename)
    return re.compile(r"!\s*" + esc + r"\s*(\|[^!\n]*)?!|\[[^\]\n]*\^\s*" + esc + r"\s*\]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="Only import the first N not-yet-imported tickets (0 = all)")
    ap.add_argument("--yes", action="store_true", help="Actually commit (otherwise dry-run and rollback)")
    args = ap.parse_args()

    idx, rows = load_csv_rows(CSV_PATH)
    print(f"Loaded {len(rows)} tickets from {CSV_PATH}")

    id_name_map = build_account_id_name_map(idx, rows)

    conn = psycopg2.connect(**DB)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("SELECT id FROM workspaces WHERE slug=%s", (WORKSPACE_SLUG,))
    row = cur.fetchone()
    if not row:
        sys.exit(f"Workspace slug={WORKSPACE_SLUG!r} not found")
    workspace_id = row[0]

    cur.execute("SELECT id FROM projects WHERE workspace_id=%s AND identifier=%s", (workspace_id, PROJECT_IDENTIFIER))
    row = cur.fetchone()
    if not row:
        sys.exit(f"Project identifier={PROJECT_IDENTIFIER!r} not found in workspace")
    project_id = row[0]

    # --- states: fetch existing, create missing ---
    cur.execute("SELECT id, name FROM states WHERE project_id=%s AND deleted_at IS NULL", (project_id,))
    state_by_name = {name: sid for sid, name in cur.fetchall()}
    now = dt.datetime.now(dt.timezone.utc)
    for name, color, group, seq in NEW_STATES:
        if name in state_by_name:
            continue
        sid = uuid.uuid4()
        cur.execute(
            """INSERT INTO states (id, created_at, updated_at, name, description, color, slug,
                   project_id, workspace_id, sequence, "group", "default", is_triage)
               VALUES (%s,%s,%s,%s,'',%s,%s,%s,%s,%s,%s,false,false)""",
            (str(sid), now, now, name, color, name.lower().replace(" ", "-"), project_id, workspace_id, seq, group),
        )
        state_by_name[name] = sid
        print(f"  created state {name!r} ({group})")

    # --- labels: fetch existing, create missing (Jira Labels + Issue Types) ---
    cur.execute("SELECT id, name FROM labels WHERE project_id=%s AND deleted_at IS NULL", (project_id,))
    label_by_name = {name: lid for lid, name in cur.fetchall()}
    jira_labels = set()
    jira_types = set()
    for r in rows:
        jira_labels.update(multi_col(idx, r, "Labels"))
        t = col(idx, r, "Issue Type")
        if t:
            jira_types.add(t)
    wanted_labels = sorted(jira_labels | jira_types)
    color_i = 0
    for name in wanted_labels:
        if name in label_by_name:
            continue
        lid = uuid.uuid4()
        color = LABEL_COLORS[color_i % len(LABEL_COLORS)]
        color_i += 1
        cur.execute(
            """INSERT INTO labels (id, created_at, updated_at, name, description, project_id,
                   workspace_id, color, sort_order)
               VALUES (%s,%s,%s,%s,'',%s,%s,%s,%s)""",
            (str(lid), now, now, name, project_id, workspace_id, color, 65536.0),
        )
        label_by_name[name] = lid
        print(f"  created label {name!r}")

    # --- users ---
    cur.execute("SELECT id, email FROM users")
    user_by_email = {email.lower(): uid for uid, email in cur.fetchall()}
    assignee_id_by_name = {
        name.lower(): user_by_email[email.lower()]
        for name, email in KNOWN_USER_EMAILS.items()
        if email.lower() in user_by_email
    }

    # --- already-imported keys (idempotency) ---
    cur.execute(
        "SELECT external_id, id FROM issues WHERE project_id=%s AND external_source=%s AND deleted_at IS NULL",
        (project_id, EXTERNAL_SOURCE),
    )
    key_to_id = {ext_id: iid for ext_id, iid in cur.fetchall()}
    already = len(key_to_id)

    # --- next sequence_id / sort_order for this project ---
    cur.execute("SELECT COALESCE(MAX(sequence_id), 0) FROM issues WHERE project_id=%s", (project_id,))
    next_seq = cur.fetchone()[0] + 1
    cur.execute("SELECT COALESCE(MAX(sort_order), 0) FROM issues WHERE project_id=%s", (project_id,))
    next_sort = cur.fetchone()[0] + 10000.0

    # sort by original Jira creation date so sequence_id roughly preserves
    # chronological order, and so parents (created earlier) are usually
    # inserted before their children
    ipos = idx["Issue key"][0]
    def sort_key(r):
        d = parse_jira_dt(col(idx, r, "Created"))
        return d or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    rows_sorted = sorted(rows, key=sort_key)

    todo = [r for r in rows_sorted if col(idx, r, "Issue key") not in key_to_id]
    if args.limit:
        todo = todo[: args.limit]

    print(f"{already} tickets already imported, {len(todo)} to import now"
          + (f" (limited to {args.limit})" if args.limit else ""))

    created_issues = created_comments = created_assignees = 0
    needs_parent_link = []  # (issue_id, parent_key)

    for r in todo:
        key = col(idx, r, "Issue key")
        summary = col(idx, r, "Summary") or key
        status = col(idx, r, "Status")
        priority = PRIORITY_MAP.get(col(idx, r, "Priority"), "none")
        assignee_name = col(idx, r, "Assignee")
        reporter_name = col(idx, r, "Reporter")
        creator_name = col(idx, r, "Creator")
        created_at = parse_jira_dt(col(idx, r, "Created")) or now
        updated_at = parse_jira_dt(col(idx, r, "Updated")) or created_at
        resolved_at = parse_jira_dt(col(idx, r, "Resolved"))
        description = col(idx, r, "Description")
        labels = multi_col(idx, r, "Labels")
        issue_type = col(idx, r, "Issue Type")
        parent_key = col(idx, r, "Parent key")
        attachments = [parse_attachment_name(a) for a in multi_col(idx, r, "Attachment")]
        freestanding_attachments = [
            a for a in attachments if not attachment_markup_pattern(a).search(description)
        ]

        state_name = STATUS_TO_STATE.get(status, "Backlog")
        state_id = state_by_name[state_name]
        is_done = state_name == "Done"

        footer_lines = [
            "", "---",
            f"*Imported from Jira ({key})*",
            f"- Original reporter: {reporter_name or 'unknown'}",
            f"- Original assignee: {assignee_name or 'unassigned'}",
            f"- Original creator: {creator_name or 'unknown'}",
            f"- Original status: {status}",
        ]
        if freestanding_attachments:
            footer_lines.append(
                f"- Attachments not migrated ({len(freestanding_attachments)}): " + ", ".join(freestanding_attachments)
            )
        full_description = (description + "\n" if description else "") + "\n".join(footer_lines)
        description_html = html_escape_paragraphs(full_description)
        description_stripped = full_description

        issue_id = uuid.uuid4()
        cur.execute(
            """INSERT INTO issues (id, created_at, updated_at, name, description_json,
                   description_html, description_stripped, priority, sequence_id,
                   project_id, state_id, workspace_id, sort_order, is_draft,
                   external_id, external_source, completed_at)
               VALUES (%s,%s,%s,%s,'{}',%s,%s,%s,%s,%s,%s,%s,%s,false,%s,%s,%s)""",
            (
                str(issue_id), created_at, updated_at, summary, description_html,
                description_stripped, priority, next_seq, project_id, state_id,
                workspace_id, next_sort, key, EXTERNAL_SOURCE,
                resolved_at if is_done else None,
            ),
        )
        cur.execute(
            """INSERT INTO issue_sequences (id, created_at, updated_at, sequence, deleted,
                   issue_id, project_id, workspace_id)
               VALUES (%s,%s,%s,%s,false,%s,%s,%s)""",
            (str(uuid.uuid4()), now, now, next_seq, str(issue_id), project_id, workspace_id),
        )
        key_to_id[key] = issue_id
        next_seq += 1
        next_sort += 10000.0
        created_issues += 1

        for label_name in labels + ([issue_type] if issue_type else []):
            lid = label_by_name.get(label_name)
            if not lid:
                continue
            cur.execute(
                """INSERT INTO issue_labels (id, created_at, updated_at, issue_id, label_id,
                       project_id, workspace_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (str(uuid.uuid4()), now, now, str(issue_id), str(lid), project_id, workspace_id),
            )

        assignee_uid = assignee_id_by_name.get(assignee_name.lower())
        if assignee_uid:
            cur.execute(
                """INSERT INTO issue_assignees (id, created_at, updated_at, assignee_id,
                       issue_id, project_id, workspace_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (str(uuid.uuid4()), now, now, str(assignee_uid), str(issue_id), project_id, workspace_id),
            )
            created_assignees += 1

        for raw_comment in multi_col(idx, r, "Comment"):
            parsed = parse_comment(raw_comment, id_name_map)
            if not parsed:
                continue
            cdate, author, text = parsed
            cdate = cdate or created_at
            comment_html = html_escape_paragraphs(f"{author}: {text}")
            cur.execute(
                """INSERT INTO issue_comments (id, created_at, updated_at, comment_stripped,
                       attachments, issue_id, project_id, workspace_id, comment_html,
                       comment_json, access)
                   VALUES (%s,%s,%s,%s,'{}',%s,%s,%s,%s,'{}','INTERNAL')""",
                (str(uuid.uuid4()), cdate, cdate, f"{author}: {text}", str(issue_id), project_id, workspace_id, comment_html),
            )
            created_comments += 1

        if parent_key:
            needs_parent_link.append((issue_id, parent_key))

    linked = 0
    for issue_id, parent_key in needs_parent_link:
        parent_id = key_to_id.get(parent_key)
        if parent_id:
            cur.execute("UPDATE issues SET parent_id=%s WHERE id=%s", (str(parent_id), str(issue_id)))
            linked += 1

    print(f"\nissues created:      {created_issues}")
    print(f"comments created:    {created_comments}")
    print(f"assignees wired up:  {created_assignees}")
    print(f"parent links set:    {linked} / {len(needs_parent_link)} (rest reference a parent not yet imported)")

    if args.yes:
        conn.commit()
        print("\nCOMMITTED.")
    else:
        conn.rollback()
        print("\nDRY RUN - rolled back, nothing was saved. Re-run with --yes to persist.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
