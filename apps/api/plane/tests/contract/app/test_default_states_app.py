# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from django.core.management import call_command
from rest_framework import status

from plane.db.models import Project, State


@pytest.mark.contract
class TestReopenedAndDuplicateStates:
    @pytest.mark.django_db
    def test_new_project_gets_reopened_and_duplicate(self, session_client, workspace):
        response = session_client.post(
            f"/api/workspaces/{workspace.slug}/projects/",
            {"name": "Fresh", "identifier": "FRESH"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        states = {state.name: state for state in State.objects.filter(project_id=response.data["id"])}
        assert states["Reopened"].group == "unstarted"
        assert states["Duplicate"].group == "cancelled"
        # Todo stays the state new work items start in
        assert [name for name, state in states.items() if state.default] == ["Todo"]

    @pytest.mark.django_db
    def test_command_adds_only_missing_states(self, workspace, create_user):
        project = Project.objects.create(name="Old", identifier="OLD", workspace=workspace, created_by=create_user)
        State.objects.create(name="Todo", group="unstarted", color="#000", default=True, project=project)
        # already there under a different case, so it must not be added twice
        State.objects.create(name="duplicate", group="cancelled", color="#111", project=project)

        call_command("add_default_states")
        call_command("add_default_states")

        names = sorted(State.all_state_objects.filter(project=project).values_list("name", flat=True))
        assert names == sorted(
            ["Backlog", "Todo", "Reopened", "In Progress", "Done", "Cancelled", "duplicate", "Triage"]
        )
        assert State.all_state_objects.get(project=project, name="duplicate").color == "#111"
        assert list(State.objects.filter(project=project, default=True).values_list("name", flat=True)) == ["Todo"]
