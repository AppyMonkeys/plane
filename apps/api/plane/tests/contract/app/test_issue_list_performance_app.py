# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status

from plane.db.models import Issue, IssueAssignee, Project, ProjectMember, State, User, WorkspaceMember


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Big", identifier="BIG", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    State.objects.create(
        name="Todo", group="unstarted", color="#000000", default=True, project=project, workspace=workspace
    )
    return project


@pytest.fixture
def teammate(db, workspace, project):
    user = User.objects.create(email="mate@plane.so", username="mate")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15, is_active=True)
    ProjectMember.objects.create(project=project, member=user, role=15, is_active=True)
    return user


def list_url(workspace, project):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/"


@pytest.mark.contract
class TestUngroupedIssueListQuery:
    """The table (spreadsheet) layout asks for an ungrouped, paginated list."""

    @pytest.mark.django_db
    def test_annotated_queries_are_not_distinct(self, session_client, workspace, project):
        """DISTINCT over the annotated rows forces every per-row subquery to run for the whole project."""
        for index in range(3):
            Issue.objects.create(name=f"Item {index}", project=project, workspace=workspace)

        with CaptureQueriesContext(connection) as queries:
            response = session_client.get(
                list_url(workspace, project),
                {
                    "order_by": "-created_at",
                    "filters": "{}",
                    "layout": "spreadsheet",
                    "cursor": "100:0:0",
                    "per_page": 100,
                },
            )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3
        annotated = [
            q["sql"] for q in queries.captured_queries if "ARRAY_AGG" in q["sql"] or '"link_count"' in q["sql"]
        ]
        assert annotated, "expected the list to run its annotated query"
        assert not [sql for sql in annotated if sql.lstrip().upper().startswith("SELECT DISTINCT")]

    @pytest.mark.django_db
    def test_filter_on_a_to_many_field_still_returns_each_item_once(
        self, session_client, workspace, project, create_user, teammate
    ):
        shared = Issue.objects.create(name="Shared", project=project, workspace=workspace)
        Issue.objects.create(name="Nobody's", project=project, workspace=workspace)
        for person in (create_user, teammate):
            IssueAssignee.objects.create(issue=shared, assignee=person, project=project, workspace=workspace)

        response = session_client.get(
            list_url(workspace, project),
            {
                "order_by": "-created_at",
                "filters": json.dumps({"and": [{"assignee_id__in": f"{create_user.id},{teammate.id}"}]}),
                "cursor": "100:0:0",
                "per_page": 100,
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert [issue["name"] for issue in response.data["results"]] == ["Shared"]
        assert sorted(str(user_id) for user_id in response.data["results"][0]["assignee_ids"]) == sorted(
            [str(create_user.id), str(teammate.id)]
        )
        assert response.data["total_results"] == 1
