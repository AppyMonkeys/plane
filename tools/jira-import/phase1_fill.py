#!/usr/bin/env python3
"""
Phase 1: through Plane's API, add what the plan says is missing:
  - tickets that are in Jira but not in Plane (with their comments and attachments)
  - comments missing on existing tickets
  - attachments missing on existing tickets

Works from the Jira cache (jira_snapshot.py) and the plan (build_plan.py), so
Jira is only contacted to download attachment files Plane lacks. Reuses the
Importer of jira_api_to_plane.py (same mapping, throttling, external_id tags and
state file), so re-running never creates duplicates.

Field fixes, renumbering and creation dates are NOT done here: they run in the
phase 3 server transaction.

  python3 phase1_fill.py --jira-project LOK --plane-project LOKKO --dry-run
  python3 phase1_fill.py --jira-project LOK --plane-project LOKKO
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import os
import sys
from types import SimpleNamespace

from build_plan import load_jira
from jira_api_to_plane import FALLBACK_MIME, Importer, Jira, Plane, load_dotenv
from runlog import STATE_DIR, RunLog


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jira-project", required=True)
    parser.add_argument("--plane-project", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Print what would be added, change nothing")
    parser.add_argument("--plane-rpm", type=float, default=45, help="Max Plane API requests per minute")
    parser.add_argument("--jira-rps", type=float, default=1, help="Max Jira requests per second")
    args = parser.parse_args()
    jira_project, plane_project = args.jira_project.upper(), args.plane_project.upper()

    plan = json.loads((STATE_DIR / f"plan_{jira_project}_to_{plane_project}.json").read_text())
    snapshot = json.loads(gzip.open(STATE_DIR / f"plane_snapshot_{plane_project}.json.gz", "rt").read())
    plane_ids = {i["external_id"].upper(): i["id"] for i in snapshot["issues"] if i["external_id"]}
    issues, _ = load_jira(jira_project)

    run = RunLog(f"phase1-{jira_project}" + ("-dry" if args.dry_run else ""))
    jira = Jira(
        os.environ.get("JIRA_BASE_URL", "https://appymonkeys.atlassian.net"),
        os.environ.get("JIRA_EMAIL", "kc@appymonkeys.com"),
        os.environ["JIRA_API_TOKEN"],
        min_interval=1 / args.jira_rps,
    )
    plane = Plane(
        os.environ.get("PLANE_BASE_URL", "https://tickets.lokkobackend.com"),
        os.environ["PLANE_API_KEY"],
        os.environ.get("PLANE_WORKSPACE_SLUG", "lokko"),
        min_interval=60 / args.plane_rpm,
    )
    importer = Importer(
        SimpleNamespace(
            jira_project=jira_project, plane_project=plane_project, dry_run=args.dry_run,
            skip_comments=False, skip_attachments=False, max_file_mb=0,
            external_source="jira_csv_import", attachment_external_source="jira_attachment_import",
            state_dir=str(STATE_DIR),
        ),
        jira,
        plane,
    )  # fmt: skip

    def cached_comments(key: str) -> list[dict]:
        """Comments from the cache, shaped like Jira's comment endpoint (renderedBody = HTML)."""
        issue = issues[key]
        rendered = {str(c["id"]): c["body"] for c in ((issue.get("renderedFields") or {}).get("comment") or {}).get("comments", [])}
        return [
            {**c, "renderedBody": rendered.get(str(c["id"]), "")}
            for c in (issue["fields"].get("comment") or {}).get("comments", [])
        ]

    importer.jira.comments = cached_comments  # no Jira calls for comments
    importer.prepare()

    # 1. tickets missing in Plane
    for key in plan["missing"]:
        try:
            before = dict(importer.stats)
            importer.import_issue(issues[key])
            if args.dry_run:
                run.ok(key, "dry-run-import", issues[key]["fields"].get("summary", "")[:80])
            else:
                plane_ids[key] = importer.state["issues"][key]
                gained = {k: importer.stats[k] - before.get(k, 0) for k in ("comments", "attachments")}
                run.ok(key, "imported", f"{plane_ids[key]} comments+{gained['comments']} attachments+{gained['attachments']}")
        except Exception as error:
            run.error(key, "import-failed", error)

    # 2. comments missing on existing tickets
    for key, comment_ids in plan["comments_missing"].items():
        fields = issues[key]["fields"]
        wanted = set(comment_ids)
        for comment in (c for c in cached_comments(key) if str(c["id"]) in wanted):
            comment_id = str(comment["id"])
            if comment_id in importer.state["comments"]:
                run.ok(key, "comment-already-done", comment_id)
                continue
            author = (comment.get("author") or {}).get("displayName", "Unknown")
            author_id = importer.user_id(comment.get("author"))
            body = importer.clean_html(comment.get("renderedBody") or "", fields.get("attachment") or []) or "<p></p>"
            if not author_id:
                body = f"<p><strong>{html.escape(author)}</strong> commented in Jira:</p>{body}"
            if args.dry_run:
                run.ok(key, "dry-run-comment", f"{comment_id} by {author} at {comment.get('created')}")
                continue
            payload = {
                "comment_html": body,
                "external_id": comment_id,
                "external_source": importer.source,
                "created_at": comment.get("created"),
            }
            if author_id:
                payload["created_by"] = author_id
            try:
                response = plane.call(
                    "POST", f"projects/{importer.pid}/work-items/{plane_ids[key]}/comments/", json=payload
                )
                if response.status_code in (200, 201):
                    run.ok(key, "comment-added", f"{comment_id} by {author}")
                elif response.status_code == 409:
                    run.ok(key, "comment-already-there", comment_id)
                else:
                    raise RuntimeError(f"HTTP {response.status_code} {response.text[:200]}")
                importer.state["comments"][comment_id] = True
                importer.save_state()
            except Exception as error:
                run.error(key, "comment-failed", f"{comment_id}: {error}")

    # 3. attachments missing on existing tickets
    for key, attachment_ids in plan["attachments_missing"].items():
        wanted = set(attachment_ids)
        for attachment in (a for a in issues[key]["fields"].get("attachment") or [] if str(a["id"]) in wanted):
            attachment_id, name = str(attachment["id"]), attachment["filename"]
            size = int(attachment.get("size") or 0)
            if args.dry_run:
                run.ok(key, "dry-run-attachment", f"{attachment_id} {name} ({size / 1e6:.1f} MB)")
                continue
            mime = attachment.get("mimeType") or FALLBACK_MIME
            try:
                before = importer.stats.get("attachments_existing", 0)
                importer.upload_attachment(
                    key, plane_ids[key], attachment_id, attachment["content"], name, mime, size
                )
                already = importer.stats.get("attachments_existing", 0) > before
                run.ok(key, "attachment-already-there" if already else "attachment-added", f"{attachment_id} {name}")
                importer.state["attachments"][attachment_id] = True
                importer.save_state()
            except Exception as error:
                run.error(key, "attachment-failed", f"{attachment_id} {name}: {error}")

    if not args.dry_run:
        importer.link_pending_parents()
    for failure in importer.failures:
        run.error("-", "importer", failure)
    run.info(f"API calls: Plane {plane.http.calls}, Jira {jira.http.calls}")
    run.close()
    return 1 if run.counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
