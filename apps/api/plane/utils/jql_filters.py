# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Translate between the JQL typed into the work items filter bar and Plane's filter expression
({"and": [{"state_id__in": "..."}, ...]}), in both directions, for one project.

Uses the JQL subset of plane/utils/jql.py: clauses joined by AND, optionally ORDER BY.
"""

# Python imports
import datetime
import re

# Django imports
from django.db.models import Q
from django.utils import timezone

# Module imports
from plane.db.models import Cycle, Issue, Label, Module, ProjectMember, State
from plane.utils.issue_types import project_issue_types
from plane.utils.jql import JQLError, parse_jql

FIELD_ALIASES = {
    "project": "project",
    "type": "type",
    "issuetype": "type",
    "work type": "type",
    "worktype": "type",
    "status": "status",
    "statuscategory": "statuscategory",
    "priority": "priority",
    "assignee": "assignee",
    "reporter": "reporter",
    "creator": "reporter",
    "labels": "labels",
    "label": "labels",
    "sprint": "sprint",
    "cycle": "sprint",
    "component": "module",
    "components": "module",
    "module": "module",
    "parent": "parent",
    "epic link": "parent",
    "parentepic": "parent",
    "text": "text",
    "textfields": "text",
    "comment": "text",
    "summary": "text",
    "description": "text",
    "key": "key",
    "issuekey": "key",
    "id": "key",
    "created": "created",
    "createddate": "created",
    "updated": "updated",
    "updateddate": "updated",
    "duedate": "due",
    "due": "due",
    "startdate": "start",
    "start date": "start",
}

# field -> the filter property it becomes
MULTI_VALUE_PROPERTIES = {
    "type": "type_id",
    "status": "state_id",
    "statuscategory": "state_group",
    "priority": "priority",
    "assignee": "assignee_id",
    "reporter": "created_by_id",
    "labels": "label_id",
    "sprint": "cycle_id",
    "module": "module_id",
    "parent": "parent_id",
}
DATE_PROPERTIES = {"created": "created_at", "updated": "updated_at", "due": "target_date", "start": "start_date"}
# fields whose every possible value is known, so != and NOT IN can be turned into IN (the rest)
NEGATABLE = {"type", "status", "statuscategory", "priority"}

PRIORITIES = {
    "highest": "urgent",
    "urgent": "urgent",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "lowest": "none",
    "none": "none",
}
STATUS_CATEGORIES = {
    "to do": ["backlog", "unstarted"],
    "todo": ["backlog", "unstarted"],
    "new": ["backlog", "unstarted"],
    "in progress": ["started"],
    "indeterminate": ["started"],
    "done": ["completed", "cancelled"],
    "complete": ["completed", "cancelled"],
}
ALL_STATE_GROUPS = ["backlog", "unstarted", "started", "completed", "cancelled"]
UNASSIGNED = "none"
MIN_DATE = "1970-01-01"
MAX_DATE = "9999-12-31"

ORDER_FIELDS = {
    "created": "created_at",
    "createddate": "created_at",
    "updated": "updated_at",
    "updateddate": "updated_at",
    "priority": "priority",
    "duedate": "target_date",
    "due": "target_date",
    "startdate": "start_date",
}

RELATIVE_DATE_RE = re.compile(r"^([+-]?\d+)\s*([mhdw])$", re.IGNORECASE)
DATE_FUNCTION_RE = re.compile(r"^(now|startofday|endofday|startofweek|startofmonth)\(\s*\)$", re.IGNORECASE)


class ProjectVocabulary:
    """Names and ids of the things a JQL clause can refer to in one project."""

    def __init__(self, project, user):
        self.project = project
        self.user = user

    def _by_name(self, queryset, kind, name):
        match = queryset.filter(name__iexact=name).first()
        if not match:
            raise JQLError(f'No {kind} called "{name}" in {self.project.identifier}')
        return str(match.id)

    def states(self):
        return State.objects.filter(project=self.project)

    def types(self):
        return project_issue_types(self.project.id).filter(is_active=True)

    def resolve(self, field, value):
        """The filter value for one JQL value of a multi-value field."""
        lowered = value.strip().lower()
        if field == "type":
            return self._by_name(self.types(), "work type", value)
        if field == "status":
            return self._by_name(self.states(), "status", value)
        if field == "statuscategory":
            if lowered not in STATUS_CATEGORIES:
                raise JQLError(f'Unknown statusCategory "{value}" (use "To Do", "In Progress" or "Done")')
            return STATUS_CATEGORIES[lowered]
        if field == "priority":
            if lowered not in PRIORITIES:
                raise JQLError(f'Unknown priority "{value}"')
            return PRIORITIES[lowered]
        if field in ("assignee", "reporter"):
            return self.member(value)
        if field == "labels":
            return self._by_name(Label.objects.filter(project=self.project), "label", value)
        if field == "sprint":
            return self._by_name(Cycle.objects.filter(project=self.project), "cycle", value)
        if field == "module":
            return self._by_name(Module.objects.filter(project=self.project), "module", value)
        if field == "parent":
            return self.work_item(value)
        raise JQLError(f'"{field}" can\'t be used here')

    def member(self, value):
        lowered = value.strip().lower()
        if lowered in ("currentuser()", "me"):
            return str(self.user.id)
        if lowered in ("empty", "null", "unassigned"):
            return UNASSIGNED
        members = ProjectMember.objects.filter(project=self.project, is_active=True).select_related("member")
        for project_member in members:
            member = project_member.member
            full_name = f"{member.first_name} {member.last_name}".strip().lower()
            if lowered in (member.email.lower(), (member.display_name or "").lower(), full_name):
                return str(member.id)
        raise JQLError(f'No one in {self.project.identifier} matches "{value}"')

    def work_item(self, value):
        match = re.match(r"^(?:([A-Za-z0-9]+)-)?(\d+)$", value.strip())
        if not match:
            raise JQLError(f'"{value}" is not a work item key like {self.project.identifier}-12')
        query = Q(workspace_id=self.project.workspace_id, sequence_id=int(match.group(2)))
        query &= Q(project__identifier__iexact=match.group(1)) if match.group(1) else Q(project=self.project)
        issue = Issue.issue_objects.filter(query).first()
        if not issue:
            raise JQLError(f"No work item {value}")
        return str(issue.id)

    def all_values(self, field):
        if field == "type":
            return [str(pk) for pk in self.types().values_list("id", flat=True)]
        if field == "status":
            return [str(pk) for pk in self.states().values_list("id", flat=True)]
        if field == "statuscategory":
            return list(ALL_STATE_GROUPS)
        return list(dict.fromkeys(PRIORITIES.values()))

    # ---- the other direction: ids back to names ----

    def names(self, property_name, ids):
        if property_name == "type_id":
            lookup = {str(t.id): t.name for t in project_issue_types(self.project.id)}
        elif property_name == "state_id":
            lookup = {str(s.id): s.name for s in self.states()}
        elif property_name == "label_id":
            lookup = {str(label.id): label.name for label in Label.objects.filter(project=self.project)}
        elif property_name == "cycle_id":
            lookup = {str(c.id): c.name for c in Cycle.objects.filter(project=self.project)}
        elif property_name == "module_id":
            lookup = {str(m.id): m.name for m in Module.objects.filter(project=self.project)}
        elif property_name in ("assignee_id", "created_by_id"):
            members = ProjectMember.objects.filter(project=self.project).select_related("member")
            lookup = {str(pm.member_id): pm.member.email for pm in members}
            lookup[str(self.user.id)] = "currentUser()"
        elif property_name == "parent_id":
            issues = Issue.all_objects.filter(id__in=ids).select_related("project")
            lookup = {str(i.id): f"{i.project.identifier}-{i.sequence_id}" for i in issues}
        else:
            lookup = {}
        return [lookup.get(value, value) for value in ids]


def parse_date_value(value, now):
    """A JQL date value as a calendar date: 2026-01-31, 2026/01/31, -7d, -2w, now(), startOfMonth() ..."""
    text = value.strip()
    relative = RELATIVE_DATE_RE.match(text)
    if relative:
        amount, unit = int(relative.group(1)), relative.group(2).lower()
        delta = {
            "m": datetime.timedelta(minutes=amount),
            "h": datetime.timedelta(hours=amount),
            "d": datetime.timedelta(days=amount),
            "w": datetime.timedelta(weeks=amount),
        }[unit]
        return (now + delta).date()
    function = DATE_FUNCTION_RE.match(text)
    if function:
        name = function.group(1).lower()
        today = now.date()
        if name == "startofweek":
            return today - datetime.timedelta(days=today.weekday())
        if name == "startofmonth":
            return today.replace(day=1)
        return today
    try:
        return datetime.date.fromisoformat(text[:10].replace("/", "-"))
    except ValueError:
        raise JQLError(f'"{value}" is not a date (use 2026-01-31, -7d, -2w or startOfMonth())')


def jql_to_filters(jql, project, user):
    """JQL -> (filter expression, order_by). Raises JQLError with a message for the person typing it."""
    query = parse_jql(jql)
    vocabulary = ProjectVocabulary(project, user)
    now = timezone.localtime(timezone.now())

    multi_values = {}  # property -> list of values (AND of several clauses intersects them)
    date_ranges = {}  # property -> [lower, upper]
    text = None

    for clause in query.clauses:
        field = FIELD_ALIASES.get(clause.field)
        if not field:
            raise JQLError(f'Unknown field "{clause.field}"')
        operator = clause.operator

        if field == "project":
            if operator not in ("=", "in") or not all(
                value.lower() in (project.identifier.lower(), project.name.lower(), str(project.id))
                for value in clause.values
            ):
                raise JQLError(f"This search is for {project.identifier} only")
            continue

        if field in ("text", "key"):
            if (field == "text" and operator != "~") or (field == "key" and operator != "="):
                raise JQLError(f"Use {'~' if field == 'text' else '='} with {clause.field}")
            if text is not None:
                raise JQLError("Only one text search can be used")
            text = clause.values[0]
            continue

        if field in DATE_PROPERTIES:
            property_name = DATE_PROPERTIES[field]
            if operator not in ("=", ">=", ">", "<=", "<"):
                raise JQLError(f"Use =, >=, >, <= or < with {clause.field}")
            day = parse_date_value(clause.values[0], now)
            lower, upper = date_ranges.get(property_name, [None, None])
            if operator in ("=", ">=", ">"):
                start = day + datetime.timedelta(days=1) if operator == ">" else day
                lower = max(lower, start) if lower else start
            if operator in ("=", "<=", "<"):
                end = day - datetime.timedelta(days=1) if operator == "<" else day
                upper = min(upper, end) if upper else end
            date_ranges[property_name] = [lower, upper]
            continue

        property_name = MULTI_VALUE_PROPERTIES[field]
        if operator in ("is", "is not"):
            if field != "assignee" or operator != "is":
                raise JQLError(f"{clause.field} IS {'NOT ' if operator == 'is not' else ''}EMPTY is not supported")
            values = [UNASSIGNED]
        elif operator in ("=", "in", "!=", "not in"):
            values = []
            for value in clause.values:
                resolved = vocabulary.resolve(field, value)
                values.extend(resolved if isinstance(resolved, list) else [resolved])
            if operator in ("!=", "not in"):
                if field not in NEGATABLE:
                    raise JQLError(f"{operator.upper()} is not supported for {clause.field}")
                values = [value for value in vocabulary.all_values(field) if value not in values]
        else:
            raise JQLError(f'"{operator}" can\'t be used with {clause.field}')

        values = list(dict.fromkeys(values))
        if property_name in multi_values:
            values = [value for value in multi_values[property_name] if value in values]
        multi_values[property_name] = values

    conditions = [{f"{name}__in": ",".join(values)} for name, values in multi_values.items()]
    for name, (lower, upper) in date_ranges.items():
        conditions.append(
            {f"{name}__range": f"{lower.isoformat() if lower else MIN_DATE},{upper.isoformat() if upper else MAX_DATE}"}
        )
    if text:
        conditions.append({"text__exact": text})

    order_by = None
    if query.order_by:
        field, descending = query.order_by[0]
        if field not in ORDER_FIELDS:
            raise JQLError(f'Can\'t ORDER BY "{field}" (use created, updated, priority, duedate or startdate)')
        order_by = ORDER_FIELDS[field]
        if order_by == "priority":
            # Plane's "-priority" lists the most urgent first, which is Jira's priority DESC
            order_by = "-priority" if descending else "priority"
        elif descending:
            order_by = f"-{order_by}"

    return ({"and": conditions} if conditions else {}), order_by


def quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def filters_to_jql(expression, order_by, project, user):
    """Filter expression -> JQL, for showing the current Basic filters in JQL mode."""
    vocabulary = ProjectVocabulary(project, user)
    reverse_fields = {
        "type_id": "type",
        "state_id": "status",
        "state_group": "statusCategory",
        "priority": "priority",
        "assignee_id": "assignee",
        "created_by_id": "reporter",
        "label_id": "labels",
        "cycle_id": "sprint",
        "module_id": "component",
        "parent_id": "parent",
    }
    reverse_dates = {
        "created_at": "created",
        "updated_at": "updated",
        "target_date": "duedate",
        "start_date": "startdate",
    }
    priorities = {"urgent": "Highest", "high": "High", "medium": "Medium", "low": "Low", "none": "Lowest"}

    conditions = []
    if isinstance(expression, dict):
        conditions = expression.get("and", [expression] if expression else [])
    clauses = [f"project = {project.identifier}"]
    for condition in conditions:
        if not isinstance(condition, dict) or len(condition) != 1:
            raise JQLError("This filter can't be shown as JQL")
        key, raw = next(iter(condition.items()))
        name, _, operator = key.rpartition("__")
        values = [value for value in str(raw).split(",") if value]
        if name == "text":
            clauses.append(f"text ~ {quote(raw)}")
        elif name in reverse_dates and operator == "range" and len(values) == 2:
            field = reverse_dates[name]
            if values[0] != MIN_DATE:
                clauses.append(f'{field} >= "{values[0]}"')
            if values[1] != MAX_DATE:
                clauses.append(f'{field} <= "{values[1]}"')
        elif name in reverse_dates and operator == "exact":
            clauses.append(f'{reverse_dates[name]} = "{raw}"')
        elif name in reverse_fields and operator in ("in", "exact"):
            field = reverse_fields[name]
            if name == "assignee_id" and values == [UNASSIGNED]:
                clauses.append("assignee IS EMPTY")
                continue
            if name == "priority":
                labels = [priorities.get(value, value) for value in values]
            elif name == "state_group":
                labels = values
            else:
                labels = [
                    "EMPTY" if value == UNASSIGNED else label
                    for value, label in zip(values, vocabulary.names(name, values))
                ]
            rendered = [label if label in ("currentUser()", "EMPTY") else quote(label) for label in labels]
            clauses.append(f"{field} = {rendered[0]}" if len(rendered) == 1 else f"{field} IN ({', '.join(rendered)})")
        else:
            raise JQLError("This filter can't be shown as JQL")

    jql = " AND ".join(clauses)
    if order_by:
        descending = order_by.startswith("-")
        field = order_by.lstrip("-")
        jira_field = {
            "created_at": "created",
            "updated_at": "updated",
            "priority": "priority",
            "target_date": "duedate",
            "start_date": "startdate",
        }.get(field)
        if jira_field:
            # see jql_to_filters: Plane's "-priority" is Jira's priority DESC
            jql += f" ORDER BY {jira_field} {'DESC' if descending else 'ASC'}"
    return jql
