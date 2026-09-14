#!/usr/bin/env python3
"""One-off: retroactively embed attachments that were already uploaded by
import_jira_attachments.py *before* it learned how to splice attachments
into the issue description (it used to only upload + leave a "not migrated"
footer note). This walks every file_assets row it already created and runs
the exact same embed_attachment() logic a fresh upload would have run.

Safe to run more than once: embed_attachment() checks whether the asset id
already appears in the description before touching it, so already-embedded
rows are a no-op. Also safe to run after import_jira_attachments.py has
picked up its new-upload embedding on its own - there's no overlap, this
only processes rows that already exist in file_assets.
"""
import argparse
import html
import json
import re

import psycopg2

DB = dict(host="plane-db", port=5432, dbname="plane", user="plane", password="plane")

# `<p>` is matched with `[^>]*` for its attributes rather than as a literal
# tag, because once a ticket has been opened in Plane's editor, its live
# server rewrites description_html and adds class/data-id attributes to
# every `<p>`.
NOT_MIGRATED_HTML_RE = re.compile(r"<p[^>]*>- Attachments not migrated \((\d+)\): ([^<]*)</p>")
NOT_MIGRATED_TEXT_RE = re.compile(r"- Attachments not migrated \((\d+)\): (.*?)(?=\n|\[📎|$)")
FOOTER_MARKER_RE = re.compile(r"<p[^>]*>---</p>")


def attachment_markup_pattern(filename, *, escape_html=False):
    # escape_html=True matches against description_html, which has been
    # through html.escape() - without this, a filename containing
    # &/</>/quotes never matches there. description_stripped is plain,
    # unescaped text, so escape_html=False (the default) is right for it.
    name = html.escape(filename) if escape_html else filename
    esc = re.escape(name)
    return re.compile(r"!\s*" + esc + r"\s*(\|[^!\n]*)?!|\[[^\]\n]*\^\s*" + esc + r"\s*\]")


def build_embed_fragment(asset_id, filename, mime_type, download_url):
    if mime_type.startswith("image/"):
        return (
            f'<image-component src="{asset_id}" id="{asset_id}" width="35%" '
            f'height="auto" alignment="left" status="uploaded"></image-component>'
        )
    safe_name = html.escape(filename)
    return f'<a href="{html.escape(download_url)}" target="_blank" rel="noopener noreferrer">📎 {safe_name}</a>'


def _strip_one_name(names_text, count, name):
    # Remove one occurrence of `name` from a ", "-joined name list without
    # re-splitting the list on "," - a filename can itself contain a literal
    # comma (seen in practice: "...PC, Mac & Linux..."), which a naive
    # split(",") would misparse as two separate names, corrupting the count.
    for sep in (f", {name}", f"{name}, ", name):
        if sep in names_text:
            return names_text.replace(sep, "", 1), count - 1
    return names_text, count


def strip_from_not_migrated_footer(description_html, description_stripped, filename):
    def html_repl(m):
        names_text, count = _strip_one_name(m.group(2), int(m.group(1)), html.escape(filename))
        if count <= 0 or not names_text.strip():
            return ""
        return f"<p>- Attachments not migrated ({count}): {names_text}</p>"

    def text_repl(m):
        names_text, count = _strip_one_name(m.group(2), int(m.group(1)), filename)
        if count <= 0 or not names_text.strip():
            return ""
        return f"- Attachments not migrated ({count}): {names_text}"

    new_html = NOT_MIGRATED_HTML_RE.sub(html_repl, description_html, count=1)
    new_stripped = NOT_MIGRATED_TEXT_RE.sub(text_repl, description_stripped, count=1)
    return new_html, new_stripped


def embed_attachment(cur, issue_id, filename, asset_id, mime_type, download_url):
    cur.execute("SELECT description_html, description_stripped FROM issues WHERE id=%s", (issue_id,))
    row = cur.fetchone()
    if not row:
        return "no-issue"
    description_html, description_stripped = row
    description_html = description_html or "<p></p>"
    description_stripped = description_stripped or ""

    if asset_id in description_html:
        return "already-embedded"

    fragment = build_embed_fragment(asset_id, filename, mime_type, download_url)
    new_html, n = attachment_markup_pattern(filename, escape_html=True).subn(fragment, description_html, count=1)
    if n:
        new_stripped = attachment_markup_pattern(filename).sub(f"[📎 {filename}]", description_stripped, count=1)
        placement = "inline"
    else:
        block = fragment if mime_type.startswith("image/") else f"<p>{fragment}</p>"
        m = FOOTER_MARKER_RE.search(description_html)
        if m:
            new_html = description_html[: m.start()] + block + description_html[m.start() :]
        else:
            new_html = description_html + block
        new_stripped = description_stripped + f"\n[📎 {filename}]"
        placement = "appended"

    new_html, new_stripped = strip_from_not_migrated_footer(new_html, new_stripped, filename)
    cur.execute(
        "UPDATE issues SET description_html=%s, description_stripped=%s WHERE id=%s",
        (new_html, new_stripped, issue_id),
    )
    return placement


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config-jira-ingestor.json")
    ap.add_argument("--yes", action="store_true", help="Actually commit (otherwise dry-run and rollback)")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    conn = psycopg2.connect(**DB)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("SELECT id FROM workspaces WHERE slug=%s", (cfg["plane"]["workspace_slug"],))
    workspace_id = cur.fetchone()[0]
    cur.execute(
        "SELECT id FROM projects WHERE workspace_id=%s AND identifier=%s",
        (workspace_id, cfg["plane"]["project_identifier"]),
    )
    project_id = cur.fetchone()[0]

    cur.execute(
        """SELECT id, issue_id, attributes FROM file_assets
           WHERE project_id=%s AND external_source=%s AND is_deleted=false AND issue_id IS NOT NULL
           ORDER BY created_at""",
        (project_id, cfg["attachment_external_source"]),
    )
    rows = cur.fetchall()
    print(f"{len(rows)} already-uploaded attachments to check")

    counts = {"inline": 0, "appended": 0, "already-embedded": 0, "no-issue": 0}
    for asset_id, issue_id, attributes in rows:
        filename = attributes.get("name")
        mime_type = attributes.get("type") or "application/octet-stream"
        if not filename:
            continue
        download_url = (
            f"/api/assets/v2/workspaces/{cfg['plane']['workspace_slug']}"
            f"/projects/{project_id}/download/{asset_id}/"
        )
        placement = embed_attachment(cur, str(issue_id), filename, str(asset_id), mime_type, download_url)
        counts[placement] = counts.get(placement, 0) + 1
        if placement in ("inline", "appended"):
            print(f"  {filename}: embedded {placement}")

    print(f"\nembedded inline:      {counts['inline']}")
    print(f"embedded (appended):  {counts['appended']}")
    print(f"already embedded:     {counts['already-embedded']}")
    print(f"no matching issue:    {counts['no-issue']}")

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
