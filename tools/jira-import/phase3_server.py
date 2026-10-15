"""
Phase 3: renumber, fix fields, fix dates. Runs INSIDE the api container in ONE
transaction (run_phase3.sh uploads it with the plan and runs it):

  docker exec -i -e PLAN=/tmp/plan.json -e DRY_RUN=1 plane-app-api-1 python manage.py shell < phase3_server.py

DRY_RUN=1 (the default) does every step and then ROLLS BACK; only DRY_RUN=0
commits. Any check failing aborts and rolls back everything.

Inside the transaction, holding the per-project lock Plane takes for every new
work item (so nobody can create one meanwhile):
  1. checks the plan is still current: every work item to renumber still has its
     planned old number, and no work item outside the plan sits on a target number
  2. renumbers: issues.sequence_id, issue_sequences.sequence, issue_versions.sequence_id
  3. applies the field fixes (state, name, priority, type, labels, assignees, parent)
     quietly: no notifications, but an issue_activities row per change like Plane
     writes itself. A field that changed since the snapshot is skipped (Plane wins).
  4. corrects the CSV import's 5h30m shift: issues.created_at and comment created_at
     set to Jira's exact time
  5. verifies: no duplicate numbers, every imported ticket has its Jira number

Output lines: "OK\\t<ticket>\\t<action>\\t<detail>" / "ERR\\t..." (split into
success.log / errors.log by run_phase3.sh) and a final PHASE3_RESULT line.
"""

import json
import os
import re
from datetime import datetime

from django.db import connection, transaction
from django.utils import timezone

from plane.db.models import (
    Issue,
    IssueActivity,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    IssueSequence,
    Label,
    Project,
    ProjectIssueType,
    ProjectMember,
    State,
    User,
)
from plane.utils.uuid import convert_uuid_to_integer

PLAN = os.environ.get("PLAN", "/tmp/plan.json")
DRY_RUN = os.environ.get("DRY_RUN", "1") != "0"
WORKSPACE = os.environ.get("WORKSPACE", "lokko")
ACTOR_EMAIL = os.environ.get("ACTOR_EMAIL", "varun.sharma@appymonkeys.com")
LABEL_COLOR = "#6B7280"

plan = json.load(open(PLAN))
counts = {}


class Abort(Exception):
    pass


class DryRunRollback(Exception):
    pass


def out(kind, key, action, detail=""):
    detail = str(detail).replace("\n", " ").replace("\t", " ")
    print(f"{kind}\t{key or '-'}\t{action}\t{detail}", flush=True)


def ok(key, action, detail=""):
    counts[action] = counts.get(action, 0) + 1
    out("OK", key, action, detail)


def err(key, action, detail=""):
    counts["ERR:" + action] = counts.get("ERR:" + action, 0) + 1
    out("ERR", key, action, detail)


def parse_time(value):
    return datetime.fromisoformat(re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value.replace("Z", "+00:00")))


def number(key):
    return int(key.rsplit("-", 1)[1])


try:
    with transaction.atomic():
        project = Project.objects.get(identifier__iexact=plan["plane_project"], workspace__slug=WORKSPACE)
        workspace_id = project.workspace_id
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [convert_uuid_to_integer(project.id)])
        actor = User.objects.get(email=ACTOR_EMAIL)
        epoch = int(timezone.now().timestamp())

        issues = {str(i.id): i for i in Issue.all_objects.filter(project=project)}
        by_external = {i.external_id.upper(): i for i in issues.values() if i.external_id}

        # -- 1. is the plan still current? -------------------------------------
        renumber = plan["renumber"]
        targets = {r["to"] for r in renumber}
        planned_ids = {r["issue_id"] for r in renumber}
        problems = []
        for r in renumber:
            issue = issues.get(r["issue_id"])
            if not issue:
                problems.append(f"{r['issue_id']} (#{r['from']}) no longer exists")
            elif issue.sequence_id != r["from"]:
                problems.append(f"#{r['from']} is now #{issue.sequence_id}")
        for issue in issues.values():
            if str(issue.id) not in planned_ids and issue.sequence_id in targets:
                problems.append(f"{plan['plane_project']}-{issue.sequence_id} ({issue.id}) is not in the plan")
        if problems:
            for problem in problems[:50]:
                err("-", "plan-stale", problem)
            raise Abort(f"plan is stale ({len(problems)} problems): take a new snapshot and rebuild the plan")
        ok("-", "plan-current", f"{len(renumber)} renumbers, {len(issues)} work items")

        # -- 2. renumber -------------------------------------------------------
        new_number = {r["issue_id"]: r["to"] for r in renumber}
        changed = []
        for issue_id, to in new_number.items():
            issue = issues[issue_id]
            old = issue.sequence_id
            issue.sequence_id = to
            changed.append(issue)
            ok(issue.external_id or "-", "renumbered", f"{plan['plane_project']}-{old} -> {plan['plane_project']}-{to}")
        Issue.all_objects.bulk_update(changed, ["sequence_id"], batch_size=500)

        sequences = list(IssueSequence.all_objects.filter(project=project, issue_id__in=list(new_number)))
        have_row = set()
        for row in sequences:
            row.sequence = new_number[str(row.issue_id)]
            have_row.add(str(row.issue_id))
        IssueSequence.all_objects.bulk_update(sequences, ["sequence"], batch_size=500)
        for issue_id in set(new_number) - have_row:
            IssueSequence.objects.create(
                issue_id=issue_id, sequence=new_number[issue_id], project=project, workspace_id=workspace_id
            )
            ok(issues[issue_id].external_id or "-", "sequence-row-created", new_number[issue_id])
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE issue_versions v SET sequence_id = i.sequence_id FROM issues i "
                "WHERE v.issue_id = i.id AND i.project_id = %s AND v.sequence_id <> i.sequence_id",
                [str(project.id)],
            )
            ok("-", "issue-versions-updated", cursor.rowcount)

        # -- 3. field fixes ----------------------------------------------------
        states = {s.name: s for s in State.objects.filter(project=project)}
        labels = {l.name: l for l in Label.objects.filter(project=project)}
        types = {
            t.issue_type.name.lower(): t.issue_type
            for t in ProjectIssueType.objects.filter(project=project).select_related("issue_type")
        }
        members = {
            m.member.email.lower(): m.member
            for m in ProjectMember.objects.filter(project=project, is_active=True).select_related("member")
        }

        def activity(issue, field, old_value, new_value, comment, old_identifier=None, new_identifier=None):
            IssueActivity.objects.create(
                issue=issue, project=project, workspace_id=workspace_id, actor=actor, verb="updated",
                field=field, old_value=old_value, new_value=new_value, comment=comment,
                old_identifier=old_identifier, new_identifier=new_identifier, epoch=epoch,
            )  # fmt: skip

        for key, fixes in plan["fixes"].items():
            issue = by_external.get(key)
            if not issue or issue.deleted_at:
                err(key, "fix-skipped", "work item missing or deleted")
                continue
            for field, fix in fixes.items():
                want, planned = fix["jira"], fix["plane"]
                try:
                    if field == "name":
                        if issue.name.strip() != (planned or ""):
                            err(key, "fix-skipped-changed", f"name changed since snapshot")
                            continue
                        old = issue.name
                        Issue.all_objects.filter(id=issue.id).update(name=want)
                        activity(issue, "name", old, want, "updated the name to")
                    elif field == "priority":
                        if issue.priority != planned:
                            err(key, "fix-skipped-changed", "priority changed since snapshot")
                            continue
                        Issue.all_objects.filter(id=issue.id).update(priority=want)
                        activity(issue, "priority", planned, want, "updated the priority to")
                    elif field == "state":
                        current = issue.state.name if issue.state_id else None
                        if current != planned:
                            err(key, "fix-skipped-changed", f"state is {current!r}, planned from {planned!r}")
                            continue
                        state = states.get(want)
                        if not state:
                            err(key, "fix-failed", f"state {want!r} not in project")
                            continue
                        completed_at = None
                        if state.group == "completed":
                            completed_at = parse_time(fix["jira_updated"]) if fix.get("jira_updated") else timezone.now()
                        Issue.all_objects.filter(id=issue.id).update(state=state, completed_at=completed_at)
                        activity(
                            issue, "state", current, state.name, "updated the state to",
                            issue.state_id, state.id,
                        )  # fmt: skip
                    elif field == "type":
                        current = issue.type.name if issue.type_id else None
                        if (current or "").lower() != (planned or "").lower():
                            err(key, "fix-skipped-changed", f"type is {current!r}")
                            continue
                        new_type = types.get((want or "").lower())
                        if not new_type:
                            err(key, "fix-failed", f"work item type {want!r} not in project")
                            continue
                        Issue.all_objects.filter(id=issue.id).update(type=new_type)
                        activity(issue, "type", current, new_type.name, "updated the type to", issue.type_id, new_type.id)
                    elif field == "parent":
                        current = issue.parent.external_id if issue.parent_id else None
                        if current != planned:
                            err(key, "fix-skipped-changed", f"parent is {current!r}")
                            continue
                        parent = by_external.get((want or "").upper())
                        if want and not parent:
                            err(key, "fix-failed", f"parent {want} not in project")
                            continue
                        Issue.all_objects.filter(id=issue.id).update(parent=parent)
                        activity(
                            issue, "parent", current, want, "updated the parent issue to",
                            issue.parent_id, parent.id if parent else None,
                        )  # fmt: skip
                    elif field == "labels":
                        rows = list(IssueLabel.objects.filter(issue=issue).select_related("label"))
                        current = sorted({r.label.name for r in rows})
                        if current != planned:
                            err(key, "fix-skipped-changed", f"labels are {current}")
                            continue
                        for name in sorted(set(want) - set(current)):
                            if name not in labels:
                                labels[name] = Label.objects.create(
                                    name=name, color=LABEL_COLOR, project=project, workspace_id=workspace_id
                                )
                                ok(key, "label-created", name)
                            IssueLabel.objects.create(
                                issue=issue, label=labels[name], project=project, workspace_id=workspace_id
                            )
                            activity(issue, "labels", "", name, "added label ", None, labels[name].id)
                        for row in rows:
                            if row.label.name not in want:
                                IssueLabel.objects.filter(id=row.id).delete()  # soft delete
                                activity(issue, "labels", row.label.name, "", "removed label ", row.label_id, None)
                    elif field == "assignees":
                        rows = list(IssueAssignee.objects.filter(issue=issue).select_related("assignee"))
                        current = sorted(r.assignee.email.lower() for r in rows)
                        if current != planned:
                            err(key, "fix-skipped-changed", f"assignees are {current}")
                            continue
                        missing = [e for e in want if e not in members]
                        if missing:
                            err(key, "fix-failed", f"not active members of the project: {missing}")
                            continue
                        for email in want:
                            if email not in current:
                                user = members[email]
                                IssueAssignee.objects.create(
                                    issue=issue, assignee=user, project=project, workspace_id=workspace_id
                                )
                                activity(issue, "assignees", "", user.display_name, "added assignee ", None, user.id)
                        for row in rows:
                            if row.assignee.email.lower() not in want:
                                IssueAssignee.objects.filter(id=row.id).delete()  # soft delete
                                activity(
                                    issue, "assignees", row.assignee.display_name, "", "removed assignee ",
                                    row.assignee_id, None,
                                )  # fmt: skip
                    elif field == "created_by":
                        if issue.created_by_id is not None:
                            err(key, "fix-skipped-changed", "creator is already set")
                            continue
                        user = User.objects.filter(email=want).first()
                        if not user:
                            err(key, "fix-failed", f"no Plane account {want}")
                            continue
                        Issue.all_objects.filter(id=issue.id).update(created_by=user)
                    else:
                        err(key, "fix-unknown-field", field)
                        continue
                    ok(key, f"fixed-{field}", f"{planned!r} -> {want!r}")
                except Exception as error:  # one bad field must not hide the others
                    err(key, "fix-failed", f"{field}: {error.__class__.__name__}: {error}")

        # -- 4. creation dates (CSV import's 5h30m shift) ----------------------
        for key, report in plan["report_only"].items():
            created = report.get("created_at")
            if not created or created.get("why") != "csv-shift":
                continue
            issue = by_external.get(key)
            if not issue or issue.created_at != parse_time(created["plane"]):
                err(key, "date-skipped", "work item missing or its created_at changed since snapshot")
                continue
            Issue.all_objects.filter(id=issue.id).update(created_at=parse_time(created["jira"]))
            ok(key, "created-at-fixed", f"{created['plane']} -> {created['jira']}")
        for row in plan["comment_dates"]:
            updated = IssueComment.all_objects.filter(
                id=row["comment_id"], issue__project=project, created_at=parse_time(row["plane"])
            ).update(created_at=parse_time(row["jira"]))
            if updated:
                ok(row["key"], "comment-date-fixed", f"{row['comment_id']} {row['plane']} -> {row['jira']}")
            else:
                err(row["key"], "comment-date-skipped", f"{row['comment_id']} missing or changed since snapshot")

        # -- 5. verify ---------------------------------------------------------
        final = list(Issue.all_objects.filter(project=project).values_list("id", "sequence_id", "external_id"))
        numbers = [n for _, n, _ in final]
        duplicates = sorted({n for n in numbers if numbers.count(n) > 1}) if len(set(numbers)) != len(numbers) else []
        if duplicates:
            raise Abort(f"duplicate numbers after renumbering: {duplicates[:20]}")
        wrong = [e for _, n, e in final if e and n != number(e)]
        if wrong:
            raise Abort(f"{len(wrong)} imported tickets don't have their Jira number, e.g. {wrong[:10]}")
        top_sequence = IssueSequence.all_objects.filter(project=project).order_by("-sequence").first()
        if top_sequence.sequence < max(numbers):
            raise Abort(f"issue_sequences max {top_sequence.sequence} < highest number {max(numbers)}")
        ok("-", "verified", f"{len(final)} work items, numbers unique, highest {max(numbers)}, next new = {top_sequence.sequence + 1}")

        if DRY_RUN:
            raise DryRunRollback()
    print(f"PHASE3_RESULT\tCOMMITTED\t{json.dumps(counts)}")
except DryRunRollback:
    print(f"PHASE3_RESULT\tDRY_RUN_ROLLED_BACK\t{json.dumps(counts)}")
except Abort as error:
    print(f"PHASE3_RESULT\tABORTED_ROLLED_BACK\t{error}")
