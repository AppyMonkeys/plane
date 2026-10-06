# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Jira-compatible endpoints, mounted at /api/jira/.

They speak the request/response shapes of the parts of Jira Cloud's REST API that small ticket tools
use, so such a tool can be pointed at Plane by changing its domain to `<host>/api/jira`:

    GET  rest/api/<v>/myself
    GET  rest/api/<v>/search/jql   (also /search, and POST)
    GET  rest/api/<v>/issue/<KEY>
    GET  rest/api/<v>/issue/<KEY>/transitions
    POST rest/api/<v>/issue/<KEY>/transitions
    GET  rest/api/<v>/issue/<KEY>/comment
    POST rest/api/<v>/issue/<KEY>/comment
    GET  browse/<KEY>              (redirects to the work item in the web app)

Auth is Jira's: HTTP Basic with the account email and, as the "API token", a Plane API key.
Jira concepts map onto Plane's: project key -> project identifier, status -> state, issue type ->
work item type, accountId -> user id. See JIRA_STATUS_TO_STATE / JIRA_PRIORITY_TO_PLANE for the
vocabulary that differs.
"""

# Python imports
import base64
import binascii
import html
import json
import re
import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone

# Django imports
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Case, Exists, IntegerField, OuterRef, Prefetch, Q, Value, When
from django.http import HttpResponseRedirect
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

# Third party imports
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

# Module imports
from .base import BaseAPIView
from plane.api.middleware.api_authentication import APIKeyAuthentication
from plane.api.rate_limit import ApiKeyRateThrottle
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import (
    Issue,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    Project,
    ProjectMember,
    State,
    User,
)
from plane.utils.host import base_host
from plane.utils.issue_types import project_issue_types
from plane.utils.jql import JQLError, parse_jql

# Jira name -> Plane name, where the two differ. Anything else is matched by its own name.
JIRA_STATUS_TO_STATE = {"to do": "Todo"}
STATE_TO_JIRA_STATUS = {"todo": "To Do"}

JIRA_PRIORITY_TO_PLANE = {"highest": "urgent", "high": "high", "medium": "medium", "low": "low", "lowest": "none"}
PLANE_PRIORITY_TO_JIRA = {"urgent": "Highest", "high": "High", "medium": "Medium", "low": "Low", "none": "Lowest"}

JIRA_STATUS_CATEGORY_TO_GROUPS = {
    "to do": ["backlog", "unstarted"],
    "new": ["backlog", "unstarted"],
    "in progress": ["started"],
    "indeterminate": ["started"],
    "done": ["completed", "cancelled"],
}

# Transition ids of Jira's stock software workflow, which tools tend to hardcode. Any Plane state
# can also be targeted with its own id (see the transitions GET).
STOCK_TRANSITIONS = {"11": "To Do", "21": "In Progress", "31": "In Review", "41": "Done"}

ISSUE_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)-(\d+)$")
RELATIVE_DATE_RE = re.compile(r"^([+-]?\d+)\s*([mhdw])$", re.IGNORECASE)
RELATIVE_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}

DEFAULT_MAX_RESULTS = 50
MAX_MAX_RESULTS = 100


def jira_error(message, http_status=status.HTTP_400_BAD_REQUEST):
    return Response({"errorMessages": [message], "errors": {}}, status=http_status)


class JiraBasicAuthentication(APIKeyAuthentication):
    """`Authorization: Basic base64(email:api_key)`, the way Jira Cloud takes an API token."""

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.lower().startswith("basic "):
            # still accept Plane's own X-Api-Key header
            return super().authenticate(request)

        try:
            email, _, token = base64.b64decode(header[6:].strip()).decode("utf-8").partition(":")
        except (binascii.Error, UnicodeDecodeError):
            raise AuthenticationFailed("Malformed Basic authorization header")
        if not token:
            raise AuthenticationFailed("The API token is missing")

        user, token = self.validate_api_token(token)
        if email.strip() and user.email.lower() != email.strip().lower():
            raise AuthenticationFailed("The email does not match the owner of this API token")
        return user, token

    def authenticate_header(self, request):
        return 'Basic realm="api"'


class JiraCompatRateThrottle(ApiKeyRateThrottle):
    def get_cache_key(self, request, view):
        return f"{self.scope}:{request.auth}" if request.auth else None


def display_name(user):
    if not user:
        return None
    return f"{user.first_name} {user.last_name}".strip() or user.display_name or user.email


def jira_user(user):
    if not user:
        return None
    return {
        "accountId": str(user.id),
        "displayName": display_name(user),
        "emailAddress": user.email,
        "active": user.is_active,
    }


def jira_datetime(value):
    """Jira's timestamp format, e.g. 2026-10-05T12:30:00.000+0000."""
    if not value:
        return None
    value = value.astimezone(datetime_timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}+0000"


def jira_status_name(state):
    if not state:
        return None
    return STATE_TO_JIRA_STATUS.get(state.name.lower(), state.name)


def iexact_any(lookup, values):
    q = Q()
    for value in values:
        q |= Q(**{f"{lookup}__iexact": value})
    return q


def text_to_comment_html(text):
    paragraphs = [html.escape(line) for line in str(text).replace("\r\n", "\n").split("\n")]
    return "".join(f"<p>{line}</p>" for line in paragraphs) or "<p></p>"


def adf_to_text(node):
    """Flatten an Atlassian Document Format body (what REST v3 sends) into plain text."""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return node.get("text", "")
    if node.get("type") == "hardBreak":
        return "\n"
    separator = "\n" if node.get("type") == "doc" else ""
    return separator.join(adf_to_text(child) for child in node.get("content") or [])


class JiraCompatBaseView(BaseAPIView):
    authentication_classes = [JiraBasicAuthentication]

    def get_throttles(self):
        return [JiraCompatRateThrottle()]

    # -- what the caller can see ---------------------------------------------

    def visible_projects(self):
        return Project.objects.filter(
            project_projectmember__member=self.request.user,
            project_projectmember__is_active=True,
            archived_at__isnull=True,
        ).distinct()

    def visible_issues(self):
        """Work items of the caller's projects; guests see their own unless the project opens up to them."""
        user = self.request.user
        return Issue.issue_objects.filter(
            Q(project__project_projectmember__role__gt=5)
            | Q(project__guest_view_all_features=True)
            | Q(created_by=user),
            project__project_projectmember__member=user,
            project__project_projectmember__is_active=True,
        ).distinct()

    def projects_imported_from(self, jira_project_key):
        """Projects holding tickets imported from the Jira project with this key.

        A tool still configured with the old Jira key ("LOK") keeps working after the tickets moved
        to a Plane project with another identifier ("LOKKO"): imported work items remember their
        Jira key as external_id. Only consulted when no Plane project goes by that key itself.
        """
        cache = self.__dict__.setdefault("_imported_projects", {})
        key = (jira_project_key or "").strip().upper()
        if key not in cache:
            if not key or self.visible_projects().filter(identifier__iexact=key).exists():
                cache[key] = []
            else:
                cache[key] = list(
                    Issue.objects.filter(external_id__istartswith=f"{key}-", project__in=self.visible_projects())
                    .values_list("project_id", flat=True)
                    .distinct()
                )
        return cache[key]

    def get_issue(self, key):
        match = ISSUE_KEY_RE.match(key or "")
        if not match:
            return None
        issues = self.with_issue_details(self.visible_issues())
        issue = issues.filter(project__identifier__iexact=match.group(1), sequence_id=int(match.group(2))).first()
        # an old Jira key ("LOK-6021") finds the work item that was imported from it
        return issue or issues.filter(external_id__iexact=key).first()

    def can_edit(self, issue):
        return ProjectMember.objects.filter(
            project_id=issue.project_id, member=self.request.user, is_active=True, role__gte=15
        ).exists()

    # -- JQL -> queryset -----------------------------------------------------

    def resolve_users(self, values):
        ids = []
        for value in values:
            if value.lower() in ("currentuser()", "currentuser"):
                ids.append(self.request.user.id)
                continue
            try:
                ids.append(uuid.UUID(value))
                continue
            except ValueError:
                pass
            ids.extend(
                User.objects.filter(Q(email__iexact=value) | Q(display_name__iexact=value)).values_list("id", flat=True)
            )
        return ids

    def resolve_date(self, value):
        relative = RELATIVE_DATE_RE.match(value)
        if relative:
            amount = int(relative.group(1))
            return timezone.now() + timedelta(**{RELATIVE_UNITS[relative.group(2).lower()]: amount})
        normalized = value.strip().replace("/", "-")
        parsed = parse_datetime(normalized.replace(" ", "T", 1)) if (" " in normalized or "T" in normalized) else None
        if parsed is None:
            day = parse_date(normalized)
            if day is None:
                raise JQLError(f"Cannot read the date '{value}'")
            parsed = datetime(day.year, day.month, day.day)
        return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed

    def membership_q(self, clause, positive):
        """Shared handling of = / != / IN / NOT IN / IS (NOT) EMPTY for set-like fields.

        `positive` is the Q (or Exists) meaning "has one of the values"; for IS it means "has any value".
        """
        if clause.operator in ("=", "in", "is not"):
            return Q(positive)
        if clause.operator in ("!=", "not in", "is"):
            return ~Q(positive)
        raise JQLError(f"Operator '{clause.operator}' is not supported for '{clause.field}'")

    def clause_to_q(self, clause):
        field, operator, values = clause.field, clause.operator, clause.values
        is_empty_check = operator in ("is", "is not")

        if field == "project":
            lookups = Q()
            for value in values:
                lookups |= Q(project__identifier__iexact=value) | Q(project__name__iexact=value)
                lookups |= Q(project_id__in=self.projects_imported_from(value))
            return self.membership_q(clause, lookups)

        if field in ("key", "issuekey", "issue", "id"):
            lookups = Q()
            for value in values:
                match = ISSUE_KEY_RE.match(value)
                if match:
                    lookups |= Q(project__identifier__iexact=match.group(1), sequence_id=int(match.group(2)))
            return self.membership_q(clause, lookups if lookups else Q(pk__in=[]))

        if field == "parent":
            lookups = Q(parent__isnull=False) if is_empty_check else Q()
            for value in values:
                match = ISSUE_KEY_RE.match(value)
                if match:
                    lookups |= Q(
                        parent__project__identifier__iexact=match.group(1), parent__sequence_id=int(match.group(2))
                    )
            return self.membership_q(clause, lookups if lookups else Q(pk__in=[]))

        if field == "status":
            names = [JIRA_STATUS_TO_STATE.get(value.lower(), value) for value in values]
            return self.membership_q(clause, iexact_any("state__name", names) if names else Q(state__isnull=False))

        if field == "statuscategory":
            groups = [group for value in values for group in JIRA_STATUS_CATEGORY_TO_GROUPS.get(value.lower(), [])]
            return self.membership_q(clause, Q(state__group__in=groups))

        if field == "priority":
            priorities = [JIRA_PRIORITY_TO_PLANE.get(value.lower(), value.lower()) for value in values]
            return self.membership_q(clause, Q(priority__in=priorities) if not is_empty_check else ~Q(priority="none"))

        if field in ("issuetype", "type"):
            return self.membership_q(clause, iexact_any("type__name", values) if values else Q(type__isnull=False))

        if field == "assignee":
            assignees = IssueAssignee.objects.filter(issue=OuterRef("pk"))
            if not is_empty_check:
                assignees = assignees.filter(assignee_id__in=self.resolve_users(values))
            return self.membership_q(clause, Exists(assignees))

        if field in ("reporter", "creator"):
            return self.membership_q(
                clause,
                Q(created_by_id__in=self.resolve_users(values)) if values else Q(created_by__isnull=False),
            )

        if field in ("labels", "label"):
            labels = IssueLabel.objects.filter(issue=OuterRef("pk"))
            if not is_empty_check:
                labels = labels.filter(iexact_any("label__name", values))
            return self.membership_q(clause, Exists(labels))

        if field in ("updated", "updateddate", "created", "createddate", "duedate", "due"):
            column = {"u": "updated_at", "c": "created_at", "d": "target_date"}[field[0]]
            if is_empty_check:
                return self.membership_q(clause, Q(**{f"{column}__isnull": False}))
            lookup = {">=": "gte", ">": "gt", "<=": "lte", "<": "lt"}.get(operator)
            if not lookup:
                raise JQLError(f"Operator '{operator}' is not supported for '{field}'")
            moment = self.resolve_date(values[0])
            return Q(**{f"{column}__{lookup}": moment.date() if column == "target_date" else moment})

        if field in ("text", "summary", "description", "comment"):
            if operator != "~":
                raise JQLError(f"Use ~ to search '{field}'")
            # every word has to appear somewhere, as in Jira's text search
            q = Q()
            for term in values[0].replace("*", " ").split():
                in_comment = Exists(IssueComment.objects.filter(issue=OuterRef("pk"), comment_stripped__icontains=term))
                q &= {
                    "summary": Q(name__icontains=term),
                    "description": Q(description_stripped__icontains=term),
                    "comment": Q(in_comment),
                    "text": Q(name__icontains=term) | Q(description_stripped__icontains=term) | Q(in_comment),
                }[field]
            return q

        raise JQLError(f"Field '{field}' does not exist or is not supported")

    def apply_jql(self, queryset, jql):
        query = parse_jql(jql)
        for clause in query.clauses:
            queryset = queryset.filter(self.clause_to_q(clause))

        ordering = []
        for field, descending in query.order_by:
            if field == "priority":
                # Highest first when descending, the way Jira ranks priorities
                queryset = queryset.annotate(
                    jira_priority_rank=Case(
                        *[When(priority=name, then=Value(rank)) for rank, name in enumerate(PLANE_PRIORITY_TO_JIRA)],
                        default=Value(len(PLANE_PRIORITY_TO_JIRA)),
                        output_field=IntegerField(),
                    )
                )
                ordering.append("jira_priority_rank" if descending else "-jira_priority_rank")
                continue
            column = {
                "updated": "updated_at",
                "updateddate": "updated_at",
                "created": "created_at",
                "createddate": "created_at",
                "duedate": "target_date",
                "due": "target_date",
                "key": "sequence_id",
                "issuekey": "sequence_id",
                "id": "sequence_id",
                "summary": "name",
                "status": "state__sequence",
                "rank": "sort_order",
            }.get(field)
            if not column:
                raise JQLError(f"Cannot order by '{field}'")
            ordering.append(f"-{column}" if descending else column)

        # a stable tail so pages never overlap
        return queryset.order_by(*(ordering or ["-created_at"]), "-sequence_id", "id")

    # -- Plane -> Jira JSON --------------------------------------------------

    def with_issue_details(self, queryset, with_comments=True):
        queryset = queryset.select_related(
            "state", "type", "project", "created_by", "parent__project"
        ).prefetch_related(
            Prefetch(
                "issue_assignee",
                queryset=IssueAssignee.objects.select_related("assignee").order_by("created_at"),
                to_attr="jira_assignees",
            ),
            Prefetch(
                "label_issue",
                queryset=IssueLabel.objects.select_related("label").order_by("label__name"),
                to_attr="jira_labels",
            ),
        )
        if with_comments:
            queryset = queryset.prefetch_related(
                Prefetch(
                    "issue_comments",
                    queryset=IssueComment.objects.select_related("actor").order_by("created_at"),
                    to_attr="jira_comments",
                )
            )
        return queryset

    def type_names(self, project):
        """Lower-cased work item type names of a project (cached per request)."""
        cache = self.__dict__.setdefault("_type_names", {})
        if project.id not in cache:
            cache[project.id] = (
                {name.lower() for name in project_issue_types(project.id).values_list("name", flat=True)}
                if project.is_issue_type_enabled
                else set()
            )
        return cache[project.id]

    def issue_key(self, issue):
        return f"{issue.project.identifier}-{issue.sequence_id}"

    def serialize_comment(self, comment):
        return {
            "id": str(comment.id),
            "author": jira_user(comment.actor),
            "body": comment.comment_stripped or "",
            "created": jira_datetime(comment.created_at),
            "updated": jira_datetime(comment.updated_at),
        }

    def serialize_issue(self, issue, requested_fields=None):
        user = self.request.user
        assignees = [link.assignee for link in getattr(issue, "jira_assignees", []) if link.assignee]
        # Jira has one assignee, Plane several: show the caller when they are one of them.
        assignee = next((person for person in assignees if person.id == user.id), assignees[0] if assignees else None)

        # Types that came over from Jira as labels still sit next to the real type; leave those out.
        type_names = self.type_names(issue.project)
        labels = [
            link.label.name
            for link in getattr(issue, "jira_labels", [])
            if link.label and link.label.name.lower() not in type_names
        ]

        fields = {
            "summary": issue.name,
            "description": issue.description_stripped or "",
            "status": {"id": str(issue.state_id), "name": jira_status_name(issue.state)} if issue.state else None,
            "priority": {"name": PLANE_PRIORITY_TO_JIRA.get(issue.priority, "Lowest")},
            "issuetype": {"id": str(issue.type_id), "name": issue.type.name} if issue.type else {"name": "Task"},
            "assignee": jira_user(assignee),
            "reporter": jira_user(issue.created_by),
            "project": {"id": str(issue.project_id), "key": issue.project.identifier, "name": issue.project.name},
            "created": jira_datetime(issue.created_at),
            "updated": jira_datetime(issue.updated_at),
            "duedate": issue.target_date.isoformat() if issue.target_date else None,
            "labels": labels,
            "parent": {"id": str(issue.parent_id), "key": self.issue_key(issue.parent)} if issue.parent else None,
        }
        if hasattr(issue, "jira_comments"):
            comments = [self.serialize_comment(comment) for comment in issue.jira_comments]
            fields["comment"] = {
                "comments": comments,
                "total": len(comments),
                "maxResults": len(comments),
                "startAt": 0,
            }

        if requested_fields:
            fields = {name: value for name, value in fields.items() if name in requested_fields}

        return {
            "id": str(issue.id),
            "key": self.issue_key(issue),
            "self": f"{self.api_root()}/issue/{self.issue_key(issue)}",
            "fields": fields,
        }

    def api_root(self):
        return self.request.build_absolute_uri("/api/jira/rest/api/2").rstrip("/")

    def requested_fields(self, raw):
        """The `fields` parameter as a set, or None for "everything"."""
        if isinstance(raw, (list, tuple)):
            raw = ",".join(str(item) for item in raw)
        names = {name.strip() for name in (raw or "").split(",") if name.strip()}
        if not names or names & {"*all", "*navigable"}:
            return None
        return names


class JiraMyselfEndpoint(JiraCompatBaseView):
    @extend_schema(exclude=True)
    def get(self, request, version):
        return Response({**jira_user(request.user), "self": f"{self.api_root()}/myself"}, status=status.HTTP_200_OK)


class JiraSearchEndpoint(JiraCompatBaseView):
    def search(self, request, params):
        try:
            max_results = min(max(int(params.get("maxResults") or DEFAULT_MAX_RESULTS), 1), MAX_MAX_RESULTS)
            start_at = max(int(params.get("nextPageToken") or params.get("startAt") or 0), 0)
        except (TypeError, ValueError):
            return jira_error("maxResults, startAt and nextPageToken must be numbers")

        requested_fields = self.requested_fields(params.get("fields"))
        try:
            queryset = self.apply_jql(self.visible_issues(), params.get("jql"))
        except JQLError as error:
            return jira_error(str(error))

        with_comments = requested_fields is None or "comment" in requested_fields
        page = list(self.with_issue_details(queryset, with_comments)[start_at : start_at + max_results + 1])
        is_last = len(page) <= max_results
        issues = [self.serialize_issue(issue, requested_fields) for issue in page[:max_results]]

        payload = {
            "issues": issues,
            "startAt": start_at,
            "maxResults": max_results,
            "total": start_at + len(issues) if is_last else queryset.count(),
            "isLast": is_last,
        }
        if not is_last:
            payload["nextPageToken"] = str(start_at + max_results)
        return Response(payload, status=status.HTTP_200_OK)

    @extend_schema(exclude=True)
    def get(self, request, version):
        return self.search(request, request.query_params)

    @extend_schema(exclude=True)
    def post(self, request, version):
        return self.search(request, request.data if isinstance(request.data, dict) else {})


class JiraIssueEndpoint(JiraCompatBaseView):
    @extend_schema(exclude=True)
    def get(self, request, version, key):
        issue = self.get_issue(key)
        if not issue:
            return jira_error(
                "Issue does not exist or you do not have permission to see it.", status.HTTP_404_NOT_FOUND
            )
        return Response(
            self.serialize_issue(issue, self.requested_fields(request.query_params.get("fields"))),
            status=status.HTTP_200_OK,
        )


class JiraIssueTransitionsEndpoint(JiraCompatBaseView):
    def project_states(self, issue):
        return State.objects.filter(project_id=issue.project_id).order_by("sequence")

    @extend_schema(exclude=True)
    def get(self, request, version, key):
        issue = self.get_issue(key)
        if not issue:
            return jira_error(
                "Issue does not exist or you do not have permission to see it.", status.HTTP_404_NOT_FOUND
            )
        transitions = [
            {
                "id": str(state.id),
                "name": jira_status_name(state),
                "to": {"id": str(state.id), "name": jira_status_name(state)},
            }
            for state in self.project_states(issue)
            if state.id != issue.state_id
        ]
        return Response({"transitions": transitions}, status=status.HTTP_200_OK)

    @extend_schema(exclude=True)
    def post(self, request, version, key):
        issue = self.get_issue(key)
        if not issue:
            return jira_error(
                "Issue does not exist or you do not have permission to see it.", status.HTTP_404_NOT_FOUND
            )
        if not self.can_edit(issue):
            return jira_error("You do not have permission to transition this issue.", status.HTTP_403_FORBIDDEN)

        transition = request.data.get("transition") if isinstance(request.data, dict) else None
        transition_id = str((transition or {}).get("id") or "").strip()
        if not transition_id:
            return jira_error("Missing 'transition' identifier")

        states = self.project_states(issue)
        status_name = STOCK_TRANSITIONS.get(transition_id)
        if status_name:
            state = states.filter(name__iexact=JIRA_STATUS_TO_STATE.get(status_name.lower(), status_name)).first()
        else:
            try:
                state = states.filter(pk=uuid.UUID(transition_id)).first()
            except ValueError:
                state = None
        if not state:
            return jira_error(f"Transition id '{transition_id}' is not valid for this issue.")

        if state.id != issue.state_id:
            previous_state_id = issue.state_id
            issue.state = state
            issue.save()
            issue_activity.delay(
                type="issue.activity.updated",
                requested_data=json.dumps({"state_id": str(state.id)}),
                actor_id=str(request.user.id),
                issue_id=str(issue.id),
                project_id=str(issue.project_id),
                current_instance=json.dumps({"state_id": str(previous_state_id) if previous_state_id else None}),
                epoch=int(timezone.now().timestamp()),
                notification=True,
                origin=base_host(request=request, is_app=True),
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class JiraIssueCommentEndpoint(JiraCompatBaseView):
    @extend_schema(exclude=True)
    def get(self, request, version, key):
        issue = self.get_issue(key)
        if not issue:
            return jira_error(
                "Issue does not exist or you do not have permission to see it.", status.HTTP_404_NOT_FOUND
            )
        comments = [self.serialize_comment(comment) for comment in issue.jira_comments]
        return Response(
            {"comments": comments, "total": len(comments), "maxResults": len(comments), "startAt": 0},
            status=status.HTTP_200_OK,
        )

    @extend_schema(exclude=True)
    def post(self, request, version, key):
        issue = self.get_issue(key)
        if not issue:
            return jira_error(
                "Issue does not exist or you do not have permission to see it.", status.HTTP_404_NOT_FOUND
            )

        body = request.data.get("body") if isinstance(request.data, dict) else None
        text = adf_to_text(body).strip() if body else ""
        if not text:
            return jira_error("Comment body can not be empty!")

        comment = IssueComment(
            issue=issue,
            project_id=issue.project_id,
            workspace_id=issue.workspace_id,
            actor=request.user,
            comment_html=text_to_comment_html(text),
        )
        comment.save(created_by_id=request.user.id)
        issue_activity.delay(
            type="comment.activity.created",
            requested_data=json.dumps(
                {"id": str(comment.id), "comment_html": comment.comment_html}, cls=DjangoJSONEncoder
            ),
            actor_id=str(request.user.id),
            issue_id=str(issue.id),
            project_id=str(issue.project_id),
            current_instance=None,
            epoch=int(timezone.now().timestamp()),
        )
        return Response(self.serialize_comment(comment), status=status.HTTP_201_CREATED)


class JiraBrowseRedirectEndpoint(APIView):
    """`/browse/<KEY>` links, as Jira has them: send the browser to the work item in the web app."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(exclude=True)
    def get(self, request, key):
        match = ISSUE_KEY_RE.match(key)
        project = (
            Project.objects.filter(identifier__iexact=match.group(1), archived_at__isnull=True)
            .select_related("workspace")
            .order_by("created_at")
            .first()
            if match
            else None
        )
        if not project:
            return HttpResponseRedirect("/")
        return HttpResponseRedirect(f"/{project.workspace.slug}/browse/{project.identifier}-{match.group(2)}/")
