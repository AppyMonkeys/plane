# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import datetime
import json

import pytest
from django.utils import timezone
from rest_framework import status

from plane.db.models import Issue, IssueAssignee, Label, Project, ProjectMember, State, User, WorkspaceMember
from plane.utils.issue_types import enable_issue_types, project_issue_types


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Lokko", identifier="LOK", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    for name, group, default in [
        ("Todo", "unstarted", True),
        ("In Progress", "started", False),
        ("Done", "completed", False),
        ("Duplicate", "cancelled", False),
    ]:
        State.objects.create(name=name, group=group, default=default, color="#000", project=project)
    enable_issue_types(project)
    return project


@pytest.fixture
def teammate(db, workspace, project):
    user = User.objects.create(email="dev@plane.so", username="dev", display_name="dev")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15, is_active=True)
    ProjectMember.objects.create(project=project, member=user, role=15, is_active=True)
    return user


def state(project, name):
    return State.objects.get(project=project, name=name)


def work_type(project, name):
    return project_issue_types(project.id).get(name=name)


def list_names(client, workspace, project, filters):
    response = client.get(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/",
        {"filters": json.dumps(filters), "per_page": 100, "cursor": "100:0:0"},
    )
    assert response.status_code == status.HTTP_200_OK, response.data
    return sorted(issue["name"] for issue in response.data["results"])


def jql(client, workspace, project, **body):
    return client.post(f"/api/workspaces/{workspace.slug}/projects/{project.id}/jql/", body, format="json")


@pytest.mark.contract
class TestFilterBarConditions:
    @pytest.mark.django_db
    def test_unassigned_and_people(self, session_client, workspace, project, teammate):
        mine = Issue.objects.create(name="mine", project=project)
        Issue.objects.create(name="nobody", project=project)
        removed = Issue.objects.create(name="was assigned", project=project)
        IssueAssignee.objects.create(issue=mine, assignee=teammate, project=project)
        IssueAssignee.objects.create(issue=removed, assignee=teammate, project=project, deleted_at=timezone.now())

        assert list_names(session_client, workspace, project, {"assignee_id__in": "none"}) == ["nobody", "was assigned"]
        assert list_names(session_client, workspace, project, {"assignee_id__in": f"{teammate.id},none"}) == [
            "mine",
            "nobody",
            "was assigned",
        ]

    @pytest.mark.django_db
    def test_text_matches_title_description_and_key(self, session_client, workspace, project):
        Issue.objects.create(name="Login button broken", project=project)
        Issue.objects.create(name="Other", description_html="<p>the login page</p>", project=project)
        third = Issue.objects.create(name="Unrelated", project=project)

        assert list_names(session_client, workspace, project, {"text__exact": "LOGIN"}) == [
            "Login button broken",
            "Other",
        ]
        assert list_names(session_client, workspace, project, {"text__exact": f"lok-{third.sequence_id}"}) == [
            "Unrelated"
        ]

    @pytest.mark.django_db
    def test_parent(self, session_client, workspace, project):
        epic = Issue.objects.create(name="Epic", project=project)
        Issue.objects.create(name="child", parent=epic, project=project)
        Issue.objects.create(name="orphan", project=project)

        assert list_names(session_client, workspace, project, {"parent_id__in": str(epic.id)}) == ["child"]


@pytest.mark.contract
class TestJQLEndpoint:
    @pytest.mark.django_db
    def test_jql_to_filters(self, session_client, workspace, project, teammate, create_user):
        Label.objects.create(name="UI", project=project)
        response = jql(
            session_client,
            workspace,
            project,
            jql='project = LOK AND type = Bug AND status != Done AND assignee IN (currentUser(), "dev@plane.so") '
            'AND labels = ui AND text ~ "login" AND created >= -7d ORDER BY priority DESC',
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        conditions = {key: value for condition in response.data["filters"]["and"] for key, value in condition.items()}
        assert conditions["type_id__in"] == str(work_type(project, "Bug").id)
        assert set(conditions["state_id__in"].split(",")) == {
            str(state(project, name).id) for name in ["Todo", "In Progress", "Duplicate"]
        }
        assert conditions["assignee_id__in"] == f"{create_user.id},{teammate.id}"
        assert conditions["label_id__in"] == str(Label.objects.get(name="UI").id)
        assert conditions["text__exact"] == "login"
        week_ago = (timezone.localtime(timezone.now()) - datetime.timedelta(days=7)).date().isoformat()
        assert conditions["created_at__range"] == f"{week_ago},9999-12-31"
        assert response.data["order_by"] == "-priority"

    @pytest.mark.django_db
    def test_filters_round_trip_through_jql(self, session_client, workspace, project, teammate):
        filters = {
            "and": [
                {"state_id__in": f"{state(project, 'Todo').id},{state(project, 'In Progress').id}"},
                {"assignee_id__in": "none"},
                {"priority__in": "urgent"},
                {"updated_at__range": "2026-01-01,9999-12-31"},
            ]
        }
        response = jql(session_client, workspace, project, filters=filters, order_by="-created_at")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["jql"] == (
            'project = LOK AND status IN ("Todo", "In Progress") AND assignee IS EMPTY AND priority = "Highest" '
            'AND updated >= "2026-01-01" ORDER BY created DESC'
        )
        back = jql(session_client, workspace, project, jql=response.data["jql"])
        assert back.data["filters"] == filters
        assert back.data["order_by"] == "-created_at"

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "query, message",
        [
            ("status = Nope", 'No status called "Nope"'),
            ("project = OTHER", "for LOK only"),
            ("status = Done OR status = Todo", "OR is not supported"),
            ("assignee != currentUser()", "not supported for assignee"),
            ("sprint ~ x", "can't be used"),
            ("created >= tomorrowish", "is not a date"),
        ],
    )
    def test_errors_explain_the_problem(self, session_client, workspace, project, query, message):
        response = jql(session_client, workspace, project, jql=query)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert message in response.data["error"]
