#!/usr/bin/env python3
"""
Phase 0a: read-only snapshot of every ticket in a Jira project, cached to disk.

Later phases (import, verify, renumber) work from this cache, so Jira is asked
for each ticket once, not once per phase or per re-run.

  .state/jira_cache/<PROJECT>/pages/<first-key>.json   raw search pages (rendered HTML included)
  .state/jira_cache/<PROJECT>/comments/<KEY>.json      full comment list, only for tickets
                                                       with more comments than search returns
  .state/jira_cache/<PROJECT>/summary.json             keys, highest number, gaps

Resumable: pages are fetched in key order with `key > <last cached key>`, so an
interrupted run carries on where it stopped. Attachments are NOT downloaded
here, only their metadata; files are fetched later only when Plane lacks them.

Rate limit: one Jira request at a time, --jira-rps (default 1/s), with
Retry-After back-off on 429 (see Throttled in jira_api_to_plane.py).

  python3 jira_snapshot.py --jira-project LOK
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from jira_api_to_plane import Jira, load_dotenv
from runlog import STATE_DIR, RunLog

FIELDS = [
    "summary", "description", "status", "priority", "issuetype", "labels", "assignee", "reporter",
    "creator", "created", "updated", "duedate", "resolution", "parent", "attachment", "comment",
    "issuelinks", "components", "fixVersions",
]  # fmt: skip
PAGE_SIZE = 50


def key_number(key: str) -> int:
    return int(key.rsplit("-", 1)[1])


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data))
    temp.replace(path)


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jira-project", required=True, help="Jira project key, e.g. LOK")
    parser.add_argument("--jira-rps", type=float, default=1, help="Max Jira requests per second")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", args.jira_project):
        parser.error("--jira-project must be a Jira project key")
    if not os.environ.get("JIRA_API_TOKEN"):
        raise SystemExit("Missing JIRA_API_TOKEN (environment or the repo's .env)")

    project = args.jira_project.upper()
    cache = STATE_DIR / "jira_cache" / project
    pages_dir, comments_dir = cache / "pages", cache / "comments"
    pages_dir.mkdir(parents=True, exist_ok=True)
    comments_dir.mkdir(parents=True, exist_ok=True)

    run = RunLog(f"jira-snapshot-{project}")
    jira = Jira(
        os.environ.get("JIRA_BASE_URL", "https://appymonkeys.atlassian.net"),
        os.environ.get("JIRA_EMAIL", "kc@appymonkeys.com"),
        os.environ["JIRA_API_TOKEN"],
        min_interval=1 / args.jira_rps,
    )

    # resume after the highest key already cached
    cached_keys: set[str] = set()
    for page in pages_dir.glob("*.json"):
        cached_keys.update(issue["key"] for issue in json.loads(page.read_text())["issues"])
    last = max(cached_keys, key=key_number) if cached_keys else None
    if last:
        run.info(f"{len(cached_keys)} tickets already cached, resuming after {last}")

    count = jira.http.request(
        "POST", f"{jira.base}/rest/api/3/search/approximate-count", json={"jql": f"project = {project}"}
    )
    if count.status_code == 200:
        run.info(f"Jira says project {project} has about {count.json().get('count')} tickets")

    try:
        while True:
            jql = f"project = {project}" + (f" AND key > {last}" if last else "") + " ORDER BY key ASC"
            body = {"jql": jql, "maxResults": PAGE_SIZE, "fields": FIELDS, "expand": "renderedFields"}
            response = jira.http.request("POST", f"{jira.base}/rest/api/3/search/jql", json=body)
            if response.status_code != 200:
                run.error(last or "-", "search-failed", f"HTTP {response.status_code} {response.text[:300]}")
                return 1
            issues = response.json().get("issues", [])
            if not issues:
                break

            for issue in issues:
                comment = issue["fields"].get("comment") or {}
                total, have = comment.get("total", 0), len(comment.get("comments") or [])
                target = comments_dir / f"{issue['key']}.json"
                if total > have and not target.exists():
                    try:
                        write_json(target, jira.comments(issue["key"]))
                        run.ok(issue["key"], "comments-fetched", f"{total} comments (search returned {have})")
                    except Exception as error:
                        run.error(issue["key"], "comments-failed", error)

            first = issues[0]["key"]
            write_json(pages_dir / f"{key_number(first):06d}.json", {"jql": jql, "issues": issues})
            for issue in issues:
                fields = issue["fields"]
                run.ok(
                    issue["key"],
                    "cached",
                    f"attachments={len(fields.get('attachment') or [])} "
                    f"comments={(fields.get('comment') or {}).get('total', 0)}",
                )
            cached_keys.update(issue["key"] for issue in issues)
            last = issues[-1]["key"]
            if len(issues) < PAGE_SIZE:
                break
    except KeyboardInterrupt:
        run.error(last or "-", "interrupted", "re-run to resume")
        run.close()
        return 1

    numbers = sorted(key_number(k) for k in cached_keys)
    present = set(numbers)
    gaps = [n for n in range(1, numbers[-1] + 1) if n not in present] if numbers else []
    summary = {
        "project": project,
        "tickets": len(numbers),
        "lowest": numbers[0] if numbers else None,
        "highest": numbers[-1] if numbers else None,
        "gaps": gaps,
        "jira_calls": jira.http.calls,
    }
    write_json(cache / "summary.json", summary)
    run.info(
        f"{project}: {summary['tickets']} tickets, numbers {summary['lowest']}..{summary['highest']}, "
        f"{len(gaps)} gaps (deleted/moved in Jira), {jira.http.calls} Jira calls this run"
    )
    run.close()
    return 1 if run.counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
