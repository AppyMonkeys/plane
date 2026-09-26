# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest

from plane.db.models import DraftIssue, Issue, Project, State, Workspace


@pytest.fixture
def workspace(create_user):
    """Create a test workspace"""
    return Workspace.objects.create(
        name="Test Workspace",
        slug="test-workspace",
        owner=create_user,
    )


@pytest.fixture
def project(workspace, create_user):
    """Create a test project"""
    return Project.objects.create(
        name="Test Project",
        identifier="TP",
        workspace=workspace,
        created_by=create_user,
    )


@pytest.fixture
def state(project):
    """Create a test state"""
    return State.objects.create(
        name="Todo",
        project=project,
        group="backlog",
        default=True,
    )


@pytest.mark.unit
class TestIssuePriorityDefault:
    """Work items default to Jira-style "medium" priority when none is given"""

    @pytest.mark.django_db
    def test_issue_defaults_to_medium(self, workspace, project, state, create_user):
        issue = Issue.objects.create(
            name="Test Issue",
            workspace=workspace,
            project=project,
            state=state,
            created_by=create_user,
        )
        issue.refresh_from_db()
        assert issue.priority == "medium"

    @pytest.mark.django_db
    def test_explicit_priority_is_kept(self, workspace, project, state, create_user):
        issue = Issue.objects.create(
            name="Test Issue",
            workspace=workspace,
            project=project,
            state=state,
            priority="none",
            created_by=create_user,
        )
        issue.refresh_from_db()
        assert issue.priority == "none"

    @pytest.mark.django_db
    def test_draft_issue_defaults_to_medium(self, workspace, project, create_user):
        draft = DraftIssue.objects.create(
            name="Draft Issue",
            workspace=workspace,
            project=project,
            created_by=create_user,
        )
        draft.refresh_from_db()
        assert draft.priority == "medium"
