#!/usr/bin/env python3
"""
Download attachments from Jira Cloud and write them directly into Plane's
storage (MinIO) + database, matching the exact shape Plane's own upload code
produces (verified against apps/api/plane/db/models/asset.py and
apps/api/plane/api/views/issue.py in the makeplane/plane source at v1.4.2 -
the version this instance runs) - no Plane API token, no HTTP calls to Plane
at all, same low-level approach as import_jira.py.

How issues are matched: the CSV's "Attachment" columns give a Jira issue's
attachments (format "date;accountId;filename;url"); the corresponding Plane
issue is found via issues.external_id = <Jira key> AND
issues.external_source = config.issue_external_source (set by import_jira.py).

Per attachment:
  1. Download the file from Jira (Basic auth: email + API token).
  2. Skip + report if it's over max_file_size_bytes (this instance's own
     upload limit is 5MB by default, but going direct-to-storage bypasses
     that check entirely - max_file_size_bytes here is a deliberate policy
     choice, not a technical constraint, and can be raised freely).
  3. PUT the bytes to MinIO at the same key format Plane's FileAsset model
     uses: "{workspace_id}/{uuid4().hex}-{sanitized filename}".
  4. INSERT a file_assets row with entity_type='ISSUE_ATTACHMENT',
     is_uploaded=true, external_id=<Jira attachment id>,
     external_source=config.attachment_external_source (skipped if a row
     with that external_id/external_source/issue_id already exists, so
     re-running is safe).
  5. Embed it into the issue's description in the same place Jira had it:
     import_jira.py preserved Jira's raw wiki markup in the description
     text (`!file|width=..,height=..!` for inline images, `[^file]` for
     plain attachment links) instead of rendering it, specifically so this
     step could find it later. We regex-search description_html for that
     markup and swap it for a real embed - Plane's `<image-component
     src="assetId">` custom node for images, a plain download link
     otherwise - at the exact spot the markup was. If no matching markup is
     found (the attachment was on the ticket but never referenced in the
     text), the embed is appended near the end of the description instead,
     and either way the filename is removed from the "Attachments not
     migrated" footer line import_jira.py wrote, since it's not true
     anymore. Already-embedded assets (checked by asset id substring) are
     never touched twice, so this is safe to run against already-uploaded
     attachments too (see backfill_attachment_embeds.py).

Progress is tracked per Jira ticket (not per attachment) in a local JSON
file (config's progress_file, default jira_attachments_progress.json,
override with --progress-file) written after every ticket completes. A
ticket already in that file is skipped entirely on the next run without
touching the DB or Jira - this is what makes runs resumable and is what
config's max_tickets (or --max-tickets N, which overrides it) counts
against: process at most N tickets not yet marked done, 0/omitted means
"all remaining". This is in addition to, not instead of, the
file_assets-level dedup above.
"""
import argparse
import base64
import collections
import csv
import datetime as dt
import html
import http.client
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid

import boto3
import psycopg2

DB = dict(host="plane-db", port=5432, dbname="plane", user="plane", password="plane")
FALLBACK_MIME = "application/octet-stream"
DEFAULT_PROGRESS_FILE = "jira_attachments_progress.json"

# The footer line import_jira.py writes into every migrated issue's
# description (see that script) - matched here so a filename can be removed
# from it once that attachment is actually embedded. `<p>` is matched with
# `[^>]*` for its attributes rather than as a literal tag, because once a
# ticket has been opened in Plane's editor, its live server rewrites
# description_html and adds `class`/`data-id` attributes to every `<p>` -
# see the module docstring.
# description_stripped has no reliable line breaks to anchor on: once a
# ticket has been opened in Plane's editor, its live server regenerates
# description_stripped as the doc's concatenated text content with no
# paragraph separators at all - so the filename list is bounded by a
# following newline (only ever added by *this* script's own "appended"
# case, below) or, failing that, the end of the string.
NOT_MIGRATED_HTML_RE = re.compile(r"<p[^>]*>- Attachments not migrated \((\d+)\): ([^<]*)</p>")
NOT_MIGRATED_TEXT_RE = re.compile(r"- Attachments not migrated \((\d+)\): (.*?)(?=\n|\[📎|$)")
FOOTER_MARKER_RE = re.compile(r"<p[^>]*>---</p>")


def attachment_markup_pattern(filename, *, escape_html=False):
    """Matches Jira's inline image-embed markup `!file|width=..,height=..!`
    or file-link markup `[^file]` / `[alias^file]` referencing this exact
    filename - i.e. the spot in the description text where this attachment
    originally sat in Jira. `escape_html=True` matches against
    description_html, which has been through html.escape() (see
    import_jira.py) and so has `&`/`<`/`>`/quotes turned into entities in
    both the surrounding text and the filename itself - without this, a
    filename containing any of those characters (e.g. "... Mac & Linux
    ...") would never match there. description_stripped is plain,
    unescaped text, so escape_html=False (the default) is right for it."""
    name = html.escape(filename) if escape_html else filename
    esc = re.escape(name)
    return re.compile(r"!\s*" + esc + r"\s*(\|[^!\n]*)?!|\[[^\]\n]*\^\s*" + esc + r"\s*\]")


def build_embed_fragment(asset_id, filename, mime_type, download_url):
    """The embed itself, with no block wrapper. Plane's rich-text editor
    renders images via a custom `<image-component src="<assetId>">` node
    (see packages/editor/.../custom-image) - already block-level (and an
    "atom", i.e. self-contained) on its own, so it's fine spliced directly
    into a paragraph's content: ProseMirror's HTML parser splits the
    surrounding paragraph around it when the doc is next opened. Anything
    else has no such node, so it becomes a plain inline `<a>` download
    link instead - safe to nest inside a paragraph as-is."""
    if mime_type.startswith("image/"):
        return (
            f'<image-component src="{asset_id}" id="{asset_id}" width="35%" '
            f'height="auto" alignment="left" status="uploaded"></image-component>'
        )
    safe_name = html.escape(filename)
    return f'<a href="{html.escape(download_url)}" target="_blank" rel="noopener noreferrer">📎 {safe_name}</a>'


def _strip_one_name(names_text, count, name):
    """Remove one occurrence of `name` from a ", "-joined name list without
    re-splitting the list on "," - a filename can itself contain a literal
    comma (seen in practice: "...PC, Mac & Linux..."), which a naive
    split(",") would misparse as two separate names, corrupting the count."""
    for sep in (f", {name}", f"{name}, ", name):
        if sep in names_text:
            return names_text.replace(sep, "", 1), count - 1
    return names_text, count


def strip_from_not_migrated_footer(description_html, description_stripped, filename):
    """Remove `filename` from the "Attachments not migrated (N): a, b" footer
    line import_jira.py wrote (dropping the whole line if it empties out),
    since it's being embedded now."""

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
    """Splice the migrated attachment into the issue's description at the
    spot Jira's wiki markup for it used to be, or append it near the end if
    there was no such markup. Returns "inline", "appended", or
    "already-embedded" (a no-op, so this is safe to call more than once for
    the same asset)."""
    cur.execute("SELECT description_html, description_stripped FROM issues WHERE id=%s", (issue_id,))
    description_html, description_stripped = cur.fetchone()
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
        # No inline markup for it - tack the embed on just before the
        # "Imported from Jira" metadata footer (or at the very end if for
        # some reason that marker isn't there). Images are already
        # block-level on their own; anything else needs a <p> wrapper since
        # it's an inline element and this is a top-level insertion, not a
        # splice into existing text.
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


def load_progress(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        raw = f.read().strip()
    if not raw:
        # Empty/truncated file (e.g. an interrupted write) - the DB's
        # file_assets rows are the real source of truth for what's already
        # uploaded, so treat this as "no ticket-level checkpoint yet" rather
        # than crashing; already-uploaded attachments are still caught by
        # the per-attachment DB check below and skipped, just a bit slower.
        print(f"  warning: {path} is empty, rebuilding ticket progress from scratch "
              f"(already-uploaded attachments are still deduped via the DB)")
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"{path} is not valid JSON ({e}) - fix or delete it before re-running")


def save_progress(path, done_tickets):
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(done_tickets, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def load_config(path):
    with open(path) as f:
        cfg = json.load(f)
    placeholders = [k for k, v in [("jira.email", cfg["jira"]["email"]),
                                    ("jira.api_token", cfg["jira"]["api_token"])]
                    if v.startswith("REPLACE_WITH_")]
    if placeholders:
        sys.exit("config-jira-ingestor.json still has placeholder values for: " + ", ".join(placeholders))
    return cfg


def sanitize_filename(filename):
    """Mirrors plane.utils.path_validator.sanitize_filename closely enough
    for our purposes: strip control chars, normalize slashes, take basename."""
    filename = "".join(c for c in filename if not (ord(c) < 32 or ord(c) == 127))
    filename = filename.replace("\\", "/")
    return os.path.basename(filename) or uuid.uuid4().hex


def with_retry(fn, *, retries=4, backoff=2.0):
    status, headers, body = 0, {}, b""
    for attempt in range(retries):
        status, headers, body = fn()
        # 429 (rate limited) or 0 (network-level failure, see jira_download's
        # except clause below) are worth retrying; anything else - including
        # other HTTP error codes - is returned as-is for the caller to handle.
        if status in (429, 0) and attempt < retries - 1:
            wait = float(headers.get("Retry-After", backoff * (attempt + 1)))
            time.sleep(wait)
            continue
        return status, headers, body
    return status, headers, body


def jira_download(cfg, url):
    auth = base64.b64encode(f"{cfg['email']}:{cfg['api_token']}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Accept": "*/*"}

    def do():
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read()
        except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException) as e:
            # Connection reset, DNS hiccup, read timeout, a connection cut
            # short mid-download (IncompleteRead - not an OSError subclass,
            # hence the separate http.client.HTTPException branch; seen in
            # practice on large video files), etc. - a single flaky request
            # must not crash the whole batch; status 0 signals "network
            # failure" to with_retry (retried) and to the caller (counted as
            # a failed attachment, not an unhandled crash).
            return 0, {"_error": str(e)}, b""

    return with_retry(do)


def load_attachment_tasks(csv_path):
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {}
        for i, h in enumerate(header):
            idx.setdefault(h, []).append(i)
        rows = list(reader)

    key_pos = idx["Issue key"][0]
    att_positions = idx.get("Attachment", [])
    tasks = []  # (jira_key, filename, url, jira_attachment_id)
    for r in rows:
        key = r[key_pos].strip()
        for p in att_positions:
            raw = r[p].strip()
            if not raw:
                continue
            # Format is "date;accountId;filename;url", but the filename
            # itself can contain a literal semicolon (seen in practice:
            # "lava; (2).mp4") - a plain split(";", 3) then misparses the
            # url. The url is always the last field and always starts with
            # http(s) and never contains a semicolon, so anchor on that
            # instead and let the filename absorb whatever's left.
            m = re.search(r";(https?://\S+)$", raw)
            if not m:
                continue
            url = m.group(1).strip()
            parts = raw[: m.start()].split(";", 2)
            if len(parts) < 3:
                continue
            _date, _accid, filename = parts
            attachment_id = url.rstrip("/").rsplit("/", 1)[-1]
            tasks.append((key, filename.strip(), url, attachment_id))
    return tasks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config-jira-ingestor.json")
    ap.add_argument("--max-tickets", type=int, default=None,
                     help="Only process the first N tickets not already marked done (0 = all). "
                          "Overrides config's max_tickets; omit to use the config value.")
    ap.add_argument("--progress-file", default=None,
                     help="Overrides config's progress_file / the default of %s" % DEFAULT_PROGRESS_FILE)
    args = ap.parse_args()

    cfg = load_config(args.config)
    max_size = cfg["max_file_size_bytes"]
    delay = cfg["request_delay_seconds"]
    ext_source = cfg["attachment_external_source"]
    progress_path = args.progress_file or cfg.get("progress_file", DEFAULT_PROGRESS_FILE)
    max_tickets = args.max_tickets if args.max_tickets is not None else cfg.get("max_tickets", 0)

    tasks = load_attachment_tasks(cfg["csv_path"])
    tasks_by_ticket = collections.OrderedDict()
    for key, filename, url, attachment_id in tasks:
        tasks_by_ticket.setdefault(key, []).append((filename, url, attachment_id))
    print(f"{len(tasks)} attachments across {len(tasks_by_ticket)} tickets in {cfg['csv_path']}")

    done_tickets = load_progress(progress_path)
    print(f"{len(done_tickets)} tickets already marked done in {progress_path}")

    pending_tickets = [k for k in tasks_by_ticket if k not in done_tickets]
    if max_tickets:
        pending_tickets = pending_tickets[:max_tickets]
    print(f"{len(pending_tickets)} tickets to process this run"
          + (f" (limited to max_tickets={max_tickets})" if max_tickets else ""))

    s3 = boto3.client(
        "s3",
        endpoint_url=cfg["minio"]["endpoint_url"],
        aws_access_key_id=cfg["minio"]["access_key"],
        aws_secret_access_key=cfg["minio"]["secret_key"],
        config=boto3.session.Config(signature_version="s3v4"),
    )
    bucket = cfg["minio"]["bucket"]

    conn = psycopg2.connect(**DB)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SELECT id FROM workspaces WHERE slug=%s", (cfg["plane"]["workspace_slug"],))
    workspace_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM projects WHERE workspace_id=%s AND identifier=%s",
                (workspace_id, cfg["plane"]["project_identifier"]))
    project_id = cur.fetchone()[0]
    cur.execute(
        "SELECT external_id, id FROM issues WHERE project_id=%s AND external_source=%s AND deleted_at IS NULL",
        (project_id, cfg["issue_external_source"]),
    )
    key_to_issue_id = {k: str(v) for k, v in cur.fetchall()}

    cur.execute(
        "SELECT external_id FROM file_assets WHERE project_id=%s AND external_source=%s AND is_deleted=false",
        (project_id, ext_source),
    )
    already_done = {row[0] for row in cur.fetchall()}
    conn.commit()  # release the read txn, we'll open fresh small ones per-insert below

    uploaded = skipped_no_issue = skipped_too_large = skipped_duplicate = failed = 0
    embedded_inline = embedded_appended = 0
    tickets_completed = 0

    for key in pending_tickets:
        ticket_stats = {"uploaded": 0, "skipped_too_large": 0, "skipped_duplicate": 0,
                         "no_issue": False, "failed": 0, "embedded_inline": 0, "embedded_appended": 0}
        issue_id = key_to_issue_id.get(key)
        if not issue_id:
            skipped_no_issue += 1
            ticket_stats["no_issue"] = True
            print(f"  [{key}]: no matching Plane issue, marking done and skipping")
            done_tickets[key] = {**ticket_stats, "done_at": dt.datetime.now(dt.timezone.utc).isoformat()}
            save_progress(progress_path, done_tickets)
            tickets_completed += 1
            continue

        for filename, url, attachment_id in tasks_by_ticket[key]:
            if attachment_id in already_done:
                skipped_duplicate += 1
                ticket_stats["skipped_duplicate"] += 1
                continue

            status, headers, body = jira_download(cfg["jira"], url)
            if status != 200:
                failed += 1
                ticket_stats["failed"] += 1
                detail = headers.get("_error", f"HTTP {status}")
                print(f"  [{key}] {filename}: Jira download failed ({detail})")
                time.sleep(delay)
                continue

            size = len(body)
            if size > max_size:
                skipped_too_large += 1
                ticket_stats["skipped_too_large"] += 1
                print(f"  [{key}] {filename}: {size} bytes > {max_size} limit, skipping")
                time.sleep(delay)
                continue

            mime_type = (headers.get("Content-Type") or "").split(";")[0].strip()
            if not mime_type or mime_type == "application/octet-stream":
                mime_type = mimetypes.guess_type(filename)[0] or FALLBACK_MIME

            clean_name = sanitize_filename(filename)
            asset_key = f"{workspace_id}/{uuid.uuid4().hex}-{clean_name}"

            try:
                put_resp = s3.put_object(Bucket=bucket, Key=asset_key, Body=body, ContentType=mime_type)
            except Exception as e:
                failed += 1
                ticket_stats["failed"] += 1
                print(f"  [{key}] {filename}: MinIO upload failed ({e})")
                time.sleep(delay)
                continue

            now = dt.datetime.now(dt.timezone.utc)
            asset_id = uuid.uuid4()
            storage_metadata = {
                "ETag": put_resp.get("ETag", ""),
                "ContentType": mime_type,
                "ContentLength": size,
            }
            download_url = (
                f"/api/assets/v2/workspaces/{cfg['plane']['workspace_slug']}"
                f"/projects/{project_id}/download/{asset_id}/"
            )
            try:
                cur.execute(
                    """INSERT INTO file_assets (id, created_at, updated_at, attributes, asset, size,
                           workspace_id, is_deleted, is_archived, entity_type, external_id,
                           external_source, is_uploaded, issue_id, project_id, storage_metadata)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,false,false,'ISSUE_ATTACHMENT',%s,%s,true,%s,%s,%s)""",
                    (
                        str(asset_id), now, now,
                        json.dumps({"name": clean_name, "type": mime_type, "size": size}),
                        asset_key, size, workspace_id, attachment_id, ext_source,
                        issue_id, project_id, json.dumps(storage_metadata),
                    ),
                )
                placement = embed_attachment(cur, issue_id, filename, str(asset_id), mime_type, download_url)
                conn.commit()
            except Exception as e:
                conn.rollback()
                failed += 1
                ticket_stats["failed"] += 1
                print(f"  [{key}] {filename}: DB insert failed ({e})")
                time.sleep(delay)
                continue

            already_done.add(attachment_id)
            uploaded += 1
            ticket_stats["uploaded"] += 1
            if placement == "inline":
                embedded_inline += 1
                ticket_stats["embedded_inline"] += 1
            elif placement == "appended":
                embedded_appended += 1
                ticket_stats["embedded_appended"] += 1
            print(f"  [{key}] {filename}: uploaded ({size} bytes), embedded {placement}")
            time.sleep(delay)

        # Ticket is marked done once every one of its attachments has been
        # attempted, even if some failed/were skipped - this is what makes
        # --max-tickets resumable without redoing work, but it means a
        # transient failure (e.g. a flaky Jira response) won't be
        # automatically retried on a later run. Any ticket with failed>0 in
        # progress_path is reported at the end of this run so it's easy to
        # spot and re-run deliberately (delete its entry from the progress
        # file to make it pending again).
        done_tickets[key] = {**ticket_stats, "done_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        save_progress(progress_path, done_tickets)
        tickets_completed += 1

    cur.close()
    conn.close()

    failed_tickets = [k for k, v in done_tickets.items() if v.get("failed")]

    print(f"\ntickets processed this run: {tickets_completed}")
    print(f"uploaded:              {uploaded}")
    print(f"  embedded inline:     {embedded_inline}")
    print(f"  embedded (appended): {embedded_appended}")
    print(f"already imported:      {skipped_duplicate}")
    print(f"skipped (too large):   {skipped_too_large}")
    print(f"skipped (no issue):    {skipped_no_issue}")
    print(f"failed:                {failed}")
    if failed_tickets:
        print(f"\n{len(failed_tickets)} ticket(s) have at least one failed attachment "
              f"(see {progress_path}): {', '.join(failed_tickets[:20])}"
              + (" ..." if len(failed_tickets) > 20 else ""))


if __name__ == "__main__":
    main()
