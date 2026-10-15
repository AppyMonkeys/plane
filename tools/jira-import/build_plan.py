#!/usr/bin/env python3
"""
Phase 0c: compare the Jira cache with the Plane snapshot and write a plan. Offline, no API calls.

  python3 build_plan.py --jira-project LOK --plane-project LOKKO

Reads  .state/jira_cache/<JIRA>/...  (jira_snapshot.py)
       .state/plane_snapshot_<PLANE>.json.gz  (run_plane_snapshot.sh)
Writes .state/plan_<JIRA>_to_<PLANE>.json  and a readable  .state/plan_<JIRA>_to_<PLANE>.txt

Policy (agreed with the user):
  - every Jira ticket must exist in Plane; missing ones are listed for import
  - a field differing from Jira is fixed from Jira, unless someone changed that
    field in Plane after the import (Plane's "updated" activity): then Plane wins
  - missing comments / attachments are always added
  - numbering: an imported ticket gets the number of its Jira key (LOK-N -> N).
    A Plane-only ticket keeps its number unless that number is a Jira one; then it
    moves to max(everything)+1, +2, ... in its current order. Deleted Plane
    tickets count as occupying a number.
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from jira_api_to_plane import FALLBACK_STATE, PEOPLE, PRIORITY_MAP, STATUS_TO_STATE
from runlog import STATE_DIR, RunLog

# Plane activity field name -> plan field name
ACTIVITY_FIELD = {
    "state": "state", "assignees": "assignees", "name": "name", "description": "description",
    "labels": "labels", "priority": "priority", "type": "type", "parent": "parent",
}  # fmt: skip
COMMENT_TIME_SLACK = timedelta(seconds=90)  # CSV export kept comment times to the minute
# The CSV import stored Jira's IST wall-clock times as if they were UTC, so its
# tickets and comments sit 5h30m later than the real moment.
CSV_SHIFT = timedelta(hours=5, minutes=30)


def same_moment(plane_time: datetime | None, jira_time: datetime | None, slack: timedelta) -> str | None:
    """'exact' or 'csv-shift' when the times match (directly or with the CSV import's offset)."""
    if not plane_time or not jira_time:
        return None
    if abs(plane_time - jira_time) <= slack:
        return "exact"
    # the CSV export also dropped the seconds: same wall-clock minute
    if timedelta(0) <= jira_time - (plane_time - CSV_SHIFT) < timedelta(minutes=1):
        return "csv-shift"
    return None


def closest(candidates: list, jira_time: datetime | None, slack: timedelta):
    """The candidate time that matches jira_time best, or None."""
    matching = [t for t in candidates if same_moment(t, jira_time, slack)]
    if not matching:
        return None
    return min(matching, key=lambda t: min(abs(t - jira_time), abs(t - CSV_SHIFT - jira_time)))


def number(key: str) -> int:
    return int(key.rsplit("-", 1)[1])


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    value = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value.replace("Z", "+00:00"))
    return datetime.fromisoformat(value)


def text_key(markup: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", markup or ""))
    return re.sub(r"\s+", "", text).lower()[:120]


def load_jira(project: str) -> tuple[dict[str, dict], dict[str, list]]:
    cache = STATE_DIR / "jira_cache" / project
    issues: dict[str, dict] = {}
    for page in sorted((cache / "pages").glob("*.json")):
        for issue in json.loads(page.read_text())["issues"]:
            issues[issue["key"]] = issue
    comments: dict[str, list] = {}
    for key, issue in issues.items():
        full = cache / "comments" / f"{key}.json"
        if full.exists():
            comments[key] = json.loads(full.read_text())
        else:
            comments[key] = (issue["fields"].get("comment") or {}).get("comments") or []
    return issues, comments


def person_email(person: dict | None) -> str | None:
    if not person:
        return None
    return (person.get("emailAddress") or PEOPLE.get(person.get("displayName", "")) or "").lower() or None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jira-project", required=True)
    parser.add_argument("--plane-project", required=True)
    args = parser.parse_args()
    jira_project, plane_project = args.jira_project.upper(), args.plane_project.upper()

    run = RunLog(f"build-plan-{jira_project}")
    jira, jira_comments = load_jira(jira_project)
    snapshot = json.loads(gzip.open(STATE_DIR / f"plane_snapshot_{plane_project}.json.gz", "rt").read())
    plane_issues = snapshot["issues"]
    by_external = {i["external_id"].upper(): i for i in plane_issues if i["external_id"]}
    by_id = {i["id"]: i for i in plane_issues}
    issue_type_names = {(i["fields"].get("issuetype") or {}).get("name") for i in jira.values()} - {None}
    run.info(f"Jira {len(jira)} tickets | Plane {len(plane_issues)} work items, {len(by_external)} imported")

    plan = {
        "jira_project": jira_project,
        "plane_project": plane_project,
        "missing": [],
        "deleted_in_plane": [],
        "fixes": {},
        "kept_plane": {},
        "report_only": {},
        "comments_missing": {},
        "comment_dates": [],
        "attachments_missing": {},
        "attachments_bad": {},
        "renumber": [],
        "in_plane_not_in_jira": [],
    }

    for key in sorted(jira, key=number):
        issue, fields = jira[key], jira[key]["fields"]
        plane = by_external.get(key)
        if not plane:
            plan["missing"].append(key)
            run.ok(key, "plan-import", (fields.get("summary") or "")[:80])
            continue
        if plane["deleted_at"]:
            plan["deleted_in_plane"].append(key)
            run.error(key, "deleted-in-plane", f"deleted in Plane at {plane['deleted_at']}; not touched")
            continue

        edited = {ACTIVITY_FIELD[u["field"]] for u in plane["updates"] if u["field"] in ACTIVITY_FIELD}
        expected = {
            "name": (fields.get("summary") or key).strip()[:255],
            "state": STATUS_TO_STATE.get((fields.get("status") or {}).get("name", ""), FALLBACK_STATE),
            "priority": PRIORITY_MAP.get((fields.get("priority") or {}).get("name", ""), "none"),
            "type": (fields.get("issuetype") or {}).get("name"),
            "assignees": sorted(filter(None, [person_email(fields.get("assignee"))])),
            "parent": (fields.get("parent") or {}).get("key"),
        }
        parent = by_id.get(plane["parent_id"]) if plane["parent_id"] else None
        actual = {
            "name": (plane["name"] or "").strip(),
            "state": plane["state"],
            "priority": plane["priority"],
            "type": plane["type"],
            "assignees": sorted(a.lower() for a in plane["assignees"] if a),
            "parent": (parent or {}).get("external_id"),
        }
        fixes, kept = {}, []
        for field, want in expected.items():
            have = actual[field]
            same = (want or "").lower() == (have or "").lower() if field in ("type", "parent") else want == have
            if field == "parent" and want and want not in by_external and want not in plan["missing"]:
                same = True  # parent isn't a ticket of this project; recorded in the description
            if same:
                continue
            if field in edited:
                kept.append(field)
                run.ok(key, "plan-keep-plane", f"{field}: Plane {have!r} kept (edited in Plane), Jira {want!r}")
            else:
                fixes[field] = {"plane": have, "jira": want}
                if field == "state":  # completed_at for a Done state: Jira's last update, not "now"
                    fixes[field]["jira_updated"] = fields.get("updated")
                run.ok(key, "plan-fix", f"{field}: {have!r} -> {want!r}")
        # labels: Jira's labels, plus the issue-type labels the CSV import added (kept)
        want_labels = sorted(set(fields.get("labels") or []) | (set(plane["labels"]) & issue_type_names))
        if want_labels != sorted(set(plane["labels"])):
            if "labels" in edited:
                kept.append("labels")
            else:
                fixes["labels"] = {"plane": sorted(plane["labels"]), "jira": want_labels}
                run.ok(key, "plan-fix", f"labels: {sorted(plane['labels'])} -> {want_labels}")
        if fixes:
            plan["fixes"][key] = fixes
        if kept:
            plan["kept_plane"][key] = kept

        # creation date / reporter can't be changed through Plane's API: report only
        # (a wrong creation date can be corrected in the phase 3 server script)
        report = {}
        jira_created, plane_created = parse_time(fields.get("created")), parse_time(plane["created_at"])
        moment = same_moment(plane_created, jira_created, timedelta(minutes=2))
        if jira_created and plane_created and moment != "exact":
            report["created_at"] = {
                "plane": plane["created_at"],
                "jira": fields.get("created"),
                "why": "csv-shift" if moment else "other",
            }
        reporter = person_email(fields.get("reporter"))
        if reporter and plane["created_by"] and reporter != plane["created_by"].lower():
            report["created_by"] = {"plane": plane["created_by"], "jira": reporter}
        elif reporter and not plane["created_by"]:
            # the CSV import left the creator empty: the Jira reporter fills it
            plan["fixes"].setdefault(key, {})["created_by"] = {"plane": None, "jira": reporter}
            run.ok(key, "plan-fix", f"created_by: None -> {reporter!r}")
        if report:
            plan["report_only"][key] = report

        # comments: by Jira id (API import) or by time (CSV import kept the Jira time)
        plane_comments = plane["comments"]
        known_ids = {c["external_id"] for c in plane_comments if c["external_id"]}
        untagged = [(parse_time(c["created_at"]), c) for c in plane_comments if not c["external_id"]]
        missing_comments = []
        for comment in jira_comments.get(key, []):
            if str(comment["id"]) in known_ids:
                continue
            created = parse_time(comment.get("created"))
            match = closest([t for t, _ in untagged if t], created, COMMENT_TIME_SLACK)
            if match:
                index = next(i for i, (t, _) in enumerate(untagged) if t == match)
                plane_comment = untagged.pop(index)[1]
                if same_moment(match, created, COMMENT_TIME_SLACK) == "csv-shift":
                    plan["comment_dates"].append(
                        {"comment_id": plane_comment["id"], "plane": plane_comment["created_at"],
                         "jira": comment.get("created"), "jira_comment_id": str(comment["id"]), "key": key}  # fmt: skip
                    )
                continue
            missing_comments.append(str(comment["id"]))
        if missing_comments:
            plan["comments_missing"][key] = missing_comments
            run.ok(key, "plan-comments", f"{len(missing_comments)} missing")

        # attachments: by Jira attachment id
        plane_files = {a["external_id"]: a for a in plane["attachments"] if a["external_id"] and not a["deleted_at"]}
        missing_files, bad_files = [], []
        for attachment in fields.get("attachment") or []:
            have = plane_files.get(str(attachment["id"]))
            if not have:
                missing_files.append(str(attachment["id"]))
            elif not have["is_uploaded"] or int(have["size"] or 0) != int(attachment.get("size") or 0):
                bad_files.append(
                    {"id": str(attachment["id"]), "name": attachment["filename"], "jira_size": attachment.get("size"),
                     "plane_size": have["size"], "uploaded": have["is_uploaded"]}  # fmt: skip
                )
        if missing_files:
            plan["attachments_missing"][key] = missing_files
            run.ok(key, "plan-attachments", f"{len(missing_files)} missing")
        if bad_files:
            plan["attachments_bad"][key] = bad_files
            run.error(key, "attachment-mismatch", json.dumps(bad_files))

    for external_id in sorted(set(by_external) - set(jira), key=number):
        plan["in_plane_not_in_jira"].append(external_id)
        run.error(external_id, "not-in-jira", "imported ticket no longer in Jira (deleted or moved there)")

    # -- numbering --------------------------------------------------------------
    jira_numbers = {number(k) for k in jira}
    reserved = jira_numbers | {number(e) for e in by_external}  # every Jira-derived number
    highest = max(
        [*reserved, *(i["sequence_id"] for i in plane_issues), *(s["sequence"] for s in snapshot["sequences"])]
    )
    next_free = highest + 1
    for plane in sorted(plane_issues, key=lambda i: i["sequence_id"]):
        if plane["external_id"]:
            target = number(plane["external_id"])
            kind = "jira"
        elif plane["sequence_id"] in reserved:
            target, next_free = next_free, next_free + 1
            kind = "plane-only-moved"
        else:
            continue
        if target != plane["sequence_id"]:
            plan["renumber"].append(
                {"issue_id": plane["id"], "external_id": plane["external_id"], "from": plane["sequence_id"],
                 "to": target, "kind": kind, "deleted": bool(plane["deleted_at"])}  # fmt: skip
            )
    # tickets still to import will be created with a fresh number and moved to N in phase 3
    targets = [r["to"] for r in plan["renumber"]]
    assert len(targets) == len(set(targets)), "renumber plan has duplicate targets"
    staying = {i["sequence_id"] for i in plane_issues} - {r["from"] for r in plan["renumber"]}
    assert not staying & set(targets), "renumber plan collides with a ticket that keeps its number"

    out = STATE_DIR / f"plan_{jira_project}_to_{plane_project}.json"
    out.write_text(json.dumps(plan, indent=1))

    moved_plane = [r for r in plan["renumber"] if r["kind"] == "plane-only-moved"]
    fix_fields: dict[str, int] = {}
    for fixes in plan["fixes"].values():
        for field in fixes:
            fix_fields[field] = fix_fields.get(field, 0) + 1
    report_fields: dict[str, int] = {}
    for report in plan["report_only"].values():
        for field, value in report.items():
            label = f"{field}:{value['why']}" if "why" in value else field
            report_fields[label] = report_fields.get(label, 0) + 1
    lines = [
        f"Plan {jira_project} -> {plane_project}",
        f"Jira tickets: {len(jira)} (numbers {min(jira_numbers)}..{max(jira_numbers)})",
        f"Plane work items: {len(plane_issues)} ({len(by_external)} imported, "
        f"{len(plane_issues) - len(by_external)} Plane-only)",
        "",
        f"1. Import missing tickets: {len(plan['missing'])}",
        f"   {', '.join(plan['missing'][:40])}{' ...' if len(plan['missing']) > 40 else ''}",
        f"   Deleted in Plane (left deleted, listed in errors.log): {len(plan['deleted_in_plane'])}",
        f"   Imported but gone from Jira: {len(plan['in_plane_not_in_jira'])}",
        "",
        f"2. Field fixes from Jira: {len(plan['fixes'])} tickets  {fix_fields}",
        f"   Kept Plane value (edited in Plane): {len(plan['kept_plane'])} tickets",
        f"   Report only (API can't change): {len(plan['report_only'])} tickets  {report_fields}",
        f"   Missing comments: {sum(map(len, plan['comments_missing'].values()))} "
        f"on {len(plan['comments_missing'])} tickets",
        f"   CSV comments with the 5h30m date shift: {len(plan['comment_dates'])}",
        f"   Missing attachments:{sum(map(len, plan['attachments_missing'].values()))} "
        f"on {len(plan['attachments_missing'])} tickets",
        f"   Attachments with size/upload mismatch: {sum(map(len, plan['attachments_bad'].values()))}",
        "",
        f"3. Renumber: {len(plan['renumber'])} work items "
        f"({len(plan['renumber']) - len(moved_plane)} imported -> LOK number, "
        f"{len(moved_plane)} Plane-only moved to {highest + 1}..{next_free - 1})",
        "   Plane-only tickets that move:",
        *[f"     {plane_project}-{r['from']} -> {plane_project}-{r['to']}" + (" (deleted)" if r["deleted"] else "")
          for r in moved_plane],  # fmt: skip
    ]
    (STATE_DIR / f"plan_{jira_project}_to_{plane_project}.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    run.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
