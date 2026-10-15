"""
Phase 0b: read-only snapshot of one Plane project, run INSIDE the api container:

  docker exec -i -e SNAP_PROJECT=LOKKO -e SNAP_WORKSPACE=lokko plane-app-api-1 \\
      python manage.py shell < plane_snapshot_server.py

(run_plane_snapshot.sh does this and copies the result back.)

Everything happens inside a READ ONLY transaction, so Postgres itself refuses
any write. Writes /tmp/plane_snapshot_<PROJECT>.json.gz in the container with:
  - every work item of the project, including deleted, archived and draft ones
    (they still occupy a sequence number)
  - labels, assignees, comments (text fingerprint only), attachments
  - issue_sequences rows
  - "updated" activities, so the planner can tell which fields were edited in
    Plane after the import
  - which work items / comments mention "<PROJECT>-<n>" in their text
"""

import gzip
import html
import json
import os
import re

from django.db import connection, transaction

from plane.db.models import (
    FileAsset,
    Issue,
    IssueActivity,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    IssueSequence,
    IssueType,
    Label,
    Project,
    State,
    User,
)

PROJECT = os.environ.get("SNAP_PROJECT", "LOKKO")
WORKSPACE = os.environ.get("SNAP_WORKSPACE", "lokko")
OUT = f"/tmp/plane_snapshot_{PROJECT}.json.gz"
REF = re.compile(rf"\b{re.escape(PROJECT)}-(\d+)\b", re.I)


def text_key(markup):
    """Same fingerprint as Importer.text_key in jira_api_to_plane.py."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", markup or ""))
    return re.sub(r"\s+", "", text).lower()[:120]


def iso(value):
    return value.isoformat() if value else None


def refs(markup):
    return sorted({int(n) for n in REF.findall(markup or "")})


with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")

    project = Project.objects.get(identifier__iexact=PROJECT, workspace__slug=WORKSPACE)
    pid = project.id

    users = {str(u["id"]): u["email"] for u in User.objects.values("id", "email")}
    states = {str(s["id"]): s["name"] for s in State.all_objects.filter(project_id=pid).values("id", "name")}
    labels = {str(l["id"]): l["name"] for l in Label.all_objects.filter(project_id=pid).values("id", "name")}
    types = {str(t["id"]): t["name"] for t in IssueType.all_objects.values("id", "name")}

    issues = {}
    for row in Issue.all_objects.filter(project_id=pid).values(
        "id", "sequence_id", "external_id", "external_source", "name", "state_id", "priority", "type_id",
        "parent_id", "created_at", "updated_at", "created_by_id", "archived_at", "deleted_at", "is_draft",
        "description_html", "start_date", "target_date", "completed_at",
    ):  # fmt: skip
        issues[str(row["id"])] = {
            "id": str(row["id"]),
            "sequence_id": row["sequence_id"],
            "external_id": row["external_id"],
            "external_source": row["external_source"],
            "name": row["name"],
            "state": states.get(str(row["state_id"])),
            "priority": row["priority"],
            "type": types.get(str(row["type_id"])),
            "parent_id": str(row["parent_id"]) if row["parent_id"] else None,
            "created_at": iso(row["created_at"]),
            "updated_at": iso(row["updated_at"]),
            "created_by": users.get(str(row["created_by_id"])),
            "archived_at": iso(row["archived_at"]),
            "deleted_at": iso(row["deleted_at"]),
            "is_draft": row["is_draft"],
            "description_key": text_key(row["description_html"]),
            "description_len": len(row["description_html"] or ""),
            "description_refs": refs(row["description_html"]),
            "start_date": iso(row["start_date"]),
            "target_date": iso(row["target_date"]),
            "labels": [],
            "assignees": [],
            "comments": [],
            "attachments": [],
            "updates": [],
        }

    for row in IssueLabel.objects.filter(project_id=pid).values("issue_id", "label_id"):
        if str(row["issue_id"]) in issues:
            issues[str(row["issue_id"])]["labels"].append(labels.get(str(row["label_id"])))

    for row in IssueAssignee.objects.filter(project_id=pid).values("issue_id", "assignee_id"):
        if str(row["issue_id"]) in issues:
            issues[str(row["issue_id"])]["assignees"].append(users.get(str(row["assignee_id"])))

    for row in IssueComment.objects.filter(project_id=pid).values(
        "id", "issue_id", "external_id", "external_source", "actor_id", "created_at", "comment_html"
    ):
        if str(row["issue_id"]) in issues:
            issues[str(row["issue_id"])]["comments"].append(
                {
                    "id": str(row["id"]),
                    "external_id": row["external_id"],
                    "external_source": row["external_source"],
                    "actor": users.get(str(row["actor_id"])),
                    "created_at": iso(row["created_at"]),
                    "key": text_key(row["comment_html"]),
                    "refs": refs(row["comment_html"]),
                }
            )

    for row in FileAsset.all_objects.filter(project_id=pid, entity_type="ISSUE_ATTACHMENT").values(
        "id", "issue_id", "external_id", "external_source", "attributes", "size", "is_uploaded", "deleted_at"
    ):
        if str(row["issue_id"]) in issues:
            issues[str(row["issue_id"])]["attachments"].append(
                {
                    "id": str(row["id"]),
                    "external_id": row["external_id"],
                    "external_source": row["external_source"],
                    "name": (row["attributes"] or {}).get("name"),
                    "size": row["size"],
                    "is_uploaded": row["is_uploaded"],
                    "deleted_at": iso(row["deleted_at"]),
                }
            )

    for row in IssueActivity.objects.filter(project_id=pid, verb="updated").values(
        "issue_id", "field", "actor_id", "created_at"
    ):
        if str(row["issue_id"]) in issues:
            issues[str(row["issue_id"])]["updates"].append(
                {"field": row["field"], "actor": users.get(str(row["actor_id"])), "at": iso(row["created_at"])}
            )

    sequences = [
        {"issue_id": str(r["issue_id"]) if r["issue_id"] else None, "sequence": r["sequence"], "deleted": r["deleted"]}
        for r in IssueSequence.all_objects.filter(project_id=pid).values("issue_id", "sequence", "deleted")
    ]

    snapshot = {
        "project": {
            "id": str(pid),
            "identifier": project.identifier,
            "name": project.name,
            "is_issue_type_enabled": getattr(project, "is_issue_type_enabled", None),
        },
        "issues": list(issues.values()),
        "sequences": sequences,
    }

with gzip.open(OUT, "wt") as handle:
    json.dump(snapshot, handle)

numbers = [i["sequence_id"] for i in snapshot["issues"]]
print(
    f"SNAPSHOT_OK {OUT}: {len(numbers)} work items (max #{max(numbers) if numbers else 0}), "
    f"{sum(1 for i in snapshot['issues'] if i['external_id'])} with external_id, "
    f"{len(sequences)} sequence rows"
)
