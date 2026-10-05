# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from rest_framework import status

from plane.celery import app as celery_app
from plane.db.models import Issue, IssueComment, Project, ProjectMember, State, User, WorkspaceMember


@pytest.fixture(autouse=True)
def celery_eager():
    """Run Celery tasks in-process; there's no broker in the test sandbox."""
    original = celery_app.conf.task_always_eager
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    yield
    celery_app.conf.task_always_eager = original


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Test Project", identifier="TP", workspace=workspace, created_by=create_user
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    State.objects.create(
        name="Backlog",
        color="#000000",
        group="backlog",
        default=True,
        project=project,
        workspace=workspace,
        created_by=create_user,
    )
    return project


@pytest.fixture
def issue(db, project, workspace, create_user):
    return Issue.objects.create(name="Imported issue", project=project, workspace=workspace, created_by=create_user)


@pytest.fixture
def other_member(db, workspace, project):
    """Another member of the project: the original author of an imported comment."""
    user = User.objects.create(email="author@plane.so", username="comment-author")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15, is_active=True)
    ProjectMember.objects.create(project=project, member=user, role=15, is_active=True)
    return user


@pytest.mark.contract
class TestIssueCommentCreatedByContract:
    """Importers pass created_by so a comment keeps its original author."""

    def url(self, workspace, project, issue):
        return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/{issue.id}/comments/"

    @pytest.mark.django_db
    def test_created_by_sets_the_comment_author(
        self, api_key_client, workspace, project, issue, other_member, create_user
    ):
        response = api_key_client.post(
            self.url(workspace, project, issue),
            {"comment_html": "<p>Checked on build 42</p>", "created_by": str(other_member.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        comment = IssueComment.objects.get(pk=response.data["id"])
        assert comment.created_by_id == other_member.id
        # actor is the author shown in the UI; it must not stay as the API key owner
        assert comment.actor_id == other_member.id

    @pytest.mark.django_db
    def test_author_defaults_to_the_api_key_owner(self, api_key_client, workspace, project, issue, create_user):
        response = api_key_client.post(
            self.url(workspace, project, issue), {"comment_html": "<p>Plain comment</p>"}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        comment = IssueComment.objects.get(pk=response.data["id"])
        assert comment.actor_id == create_user.id
        assert comment.created_by_id == create_user.id
