#!/usr/bin/env python3
"""
Phase 4: field-by-field match report, Jira cache vs Plane snapshot. Offline, no API calls.

  ./run_plane_snapshot.sh                       # fresh Plane snapshot first
  python3 verify_match.py --jira-project LOK --plane-project LOKKO

For every Jira ticket checks: present in Plane, number (LOK-N == LOKKO-N), title,
status, priority, type, labels, assignee, reporter, parent, created date,
description, every comment, every attachment (and its size). Writes
.state/match_<JIRA>_to_<PLANE>.txt; mismatches go to errors.log with the reason.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import timedelta

from build_plan import (
    COMMENT_TIME_SLACK,
    closest,
    load_jira,
    number,
    parse_time,
    person_email,
)
from jira_api_to_plane import FALLBACK_STATE, PRIORITY_MAP, STATUS_TO_STATE
from runlog import STATE_DIR, RunLog

CHECKS = [
    "present", "number", "title", "status", "priority", "type", "labels", "assignee", "reporter",
    "parent", "created", "description", "comments", "attachments",
]  # fmt: skip


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jira-project", required=True)
    parser.add_argument("--plane-project", required=True)
    args = parser.parse_args()
    jira_project, plane_project = args.jira_project.upper(), args.plane_project.upper()

    run = RunLog(f"verify-match-{jira_project}")
    jira, jira_comments = load_jira(jira_project)
    snapshot = json.loads(gzip.open(STATE_DIR / f"plane_snapshot_{plane_project}.json.gz", "rt").read())
    by_external = {i["external_id"].upper(): i for i in snapshot["issues"] if i["external_id"]}
    by_id = {i["id"]: i for i in snapshot["issues"]}
    issue_type_names = {(i["fields"].get("issuetype") or {}).get("name") for i in jira.values()} - {None}

    result = {check: {"match": 0, "mismatch": 0, "n/a": 0} for check in CHECKS}
    reasons: dict[str, dict[str, int]] = {check: {} for check in CHECKS}
    totals = {"jira_comments": 0, "comments_found": 0, "jira_attachments": 0, "attachments_found": 0}

    def record(key: str, check: str, ok: bool | None, reason: str = "", detail: str = "") -> None:
        if ok is None:
            result[check]["n/a"] += 1
            return
        result[check]["match" if ok else "mismatch"] += 1
        if not ok:
            reasons[check][reason] = reasons[check].get(reason, 0) + 1
            run.error(key, f"mismatch-{check}", f"{reason}: {detail}")

    for key in sorted(jira, key=number):
        fields = jira[key]["fields"]
        plane = by_external.get(key)
        record(key, "present", bool(plane and not plane["deleted_at"]), "missing in Plane")
        if not plane or plane["deleted_at"]:
            continue
        edited = {u["field"] for u in plane["updates"]}

        def compare(check: str, want, have, field: str | None = None) -> None:
            same = want == have
            reason = "edited in Plane (Plane kept)" if not same and field in edited else "differs"
            record(key, check, same, reason, f"Jira {want!r} / Plane {have!r}")

        record(key, "number", plane["sequence_id"] == number(key), "number differs", f"{plane_project}-{plane['sequence_id']}")
        compare("title", (fields.get("summary") or key).strip()[:255], (plane["name"] or "").strip(), "name")
        compare(
            "status",
            STATUS_TO_STATE.get((fields.get("status") or {}).get("name", ""), FALLBACK_STATE),
            plane["state"],
            "state",
        )
        compare("priority", PRIORITY_MAP.get((fields.get("priority") or {}).get("name", ""), "none"), plane["priority"], "priority")
        compare("type", ((fields.get("issuetype") or {}).get("name") or "").lower(), (plane["type"] or "").lower(), "type")
        compare(
            "labels",
            sorted(set(fields.get("labels") or [])),
            sorted(set(plane["labels"]) - issue_type_names),  # CSV-era issue-type labels aren't Jira labels
            "labels",
        )

        assignee = fields.get("assignee")
        if not assignee:
            record(key, "assignee", None if not plane["assignees"] else False, "assigned in Plane only", str(plane["assignees"]))
        else:
            want = person_email(assignee)
            if not want:
                record(key, "assignee", False, "Jira person has no Plane account", assignee.get("displayName"))
            else:
                compare("assignee", [want], sorted(a.lower() for a in plane["assignees"] if a), "assignees")

        reporter = person_email(fields.get("reporter"))
        if not fields.get("reporter"):
            record(key, "reporter", None)
        elif not reporter:
            record(key, "reporter", False, "Jira person has no Plane account", fields["reporter"].get("displayName"))
        else:
            record(
                key, "reporter", (plane["created_by"] or "").lower() == reporter,
                "no creator in Plane (CSV import)" if not plane["created_by"] else "creator differs",
                f"Jira {reporter} / Plane {plane['created_by']}",
            )  # fmt: skip

        parent_key = (fields.get("parent") or {}).get("key")
        plane_parent = (by_id.get(plane["parent_id"]) or {}).get("external_id") if plane["parent_id"] else None
        if parent_key and parent_key not in jira:
            record(key, "parent", None)  # parent outside the project
        else:
            compare("parent", parent_key, plane_parent, "parent")

        jira_created, plane_created = parse_time(fields.get("created")), parse_time(plane["created_at"])
        record(
            key, "created", abs(jira_created - plane_created) <= timedelta(seconds=1),
            "created date differs", f"Jira {fields.get('created')} / Plane {plane['created_at']}",
        )  # fmt: skip

        has_jira_description = bool((jira[key].get("renderedFields") or {}).get("description"))
        record(
            key, "description", (plane["description_len"] > 30) if has_jira_description else None,
            "description empty in Plane", "",
        )  # fmt: skip

        # comments: by Jira id, or by time for the CSV-era ones (their dates are now exact)
        known_ids = {c["external_id"] for c in plane["comments"] if c["external_id"]}
        untagged = [parse_time(c["created_at"]) for c in plane["comments"] if not c["external_id"]]
        missing = []
        for comment in jira_comments.get(key, []):
            totals["jira_comments"] += 1
            if str(comment["id"]) in known_ids:
                totals["comments_found"] += 1
                continue
            match = closest([t for t in untagged if t], parse_time(comment.get("created")), COMMENT_TIME_SLACK)
            if match:
                untagged.remove(match)
                totals["comments_found"] += 1
            else:
                missing.append(str(comment["id"]))
        record(
            key, "comments", (not missing) if jira_comments.get(key) else None,
            "comment missing", ",".join(missing),
        )  # fmt: skip

        files = {a["external_id"]: a for a in plane["attachments"] if a["external_id"] and not a["deleted_at"]}
        bad = []
        for attachment in fields.get("attachment") or []:
            totals["jira_attachments"] += 1
            have = files.get(str(attachment["id"]))
            if have and have["is_uploaded"] and int(have["size"] or 0) == int(attachment.get("size") or 0):
                totals["attachments_found"] += 1
            else:
                size = int(attachment.get("size") or 0) / 1e6
                bad.append(f"{attachment['filename']} ({size:.1f} MB)" + ("" if have else " not uploaded"))
        record(
            key, "attachments", (not bad) if fields.get("attachment") else None,
            "attachment missing (over Plane's 10 MB limit)" if bad and all("MB" in b for b in bad) else "attachment missing",
            "; ".join(bad),
        )  # fmt: skip

    lines = [
        f"Match report {jira_project} (Jira) vs {plane_project} (Plane)",
        f"Jira tickets: {len(jira)}  |  Plane work items: {len(snapshot['issues'])} "
        f"({len(by_external)} from Jira)",
        "",
        f"{'check':<13}{'match':>8}{'mismatch':>10}{'n/a':>7}   reasons",
    ]
    for check in CHECKS:
        r = result[check]
        why = "; ".join(f"{reason} x{count}" for reason, count in sorted(reasons[check].items(), key=lambda x: -x[1]))
        lines.append(f"{check:<13}{r['match']:>8}{r['mismatch']:>10}{r['n/a']:>7}   {why}")
    lines += [
        "",
        f"Comments: {totals['comments_found']} of {totals['jira_comments']} Jira comments found in Plane",
        f"Attachments: {totals['attachments_found']} of {totals['jira_attachments']} Jira attachments in Plane "
        "(same size, uploaded)",
        "n/a = nothing to compare (e.g. no assignee, no comments, parent outside the project)",
    ]
    (STATE_DIR / f"match_{jira_project}_to_{plane_project}.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    run.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
