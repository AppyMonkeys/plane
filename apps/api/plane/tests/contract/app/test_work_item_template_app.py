# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import Project, ProjectMember, User, WorkItemTemplate, WorkspaceMember


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Tmpl", identifier="TMPL", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


def client_for(workspace, project, email, role):
    user = User.objects.create(email=email, username=email.split("@")[0])
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role, is_active=True)
    ProjectMember.objects.create(project=project, member=user, role=role, is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def url(workspace, project, pk=None):
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/work-item-templates/"
    return f"{base}{pk}/" if pk else base


@pytest.mark.contract
class TestWorkItemTemplates:
    @pytest.mark.django_db
    def test_create_keeps_only_work_item_fields(self, session_client, workspace, project):
        response = session_client.post(
            url(workspace, project),
            {
                "name": "  Bug report ",
                "template_data": {
                    "name": "[Bug] ",
                    "description_html": "<p>Steps</p>",
                    "priority": "high",
                    "label_ids": ["a", "b"],
                    "sequence_id": 99,
                    "assignee_ids": None,
                },
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "Bug report"
        assert response.data["template_data"] == {
            "name": "[Bug] ",
            "description_html": "<p>Steps</p>",
            "priority": "high",
            "label_ids": ["a", "b"],
        }
        assert response.data["project_id"] == project.id

    @pytest.mark.django_db
    def test_rejects_wrong_field_types(self, session_client, workspace, project):
        response = session_client.post(
            url(workspace, project), {"name": "x", "template_data": {"label_ids": "a"}}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_duplicate_name_is_rejected(self, session_client, workspace, project):
        WorkItemTemplate.objects.create(name="Bug", project=project)
        response = session_client.post(url(workspace, project), {"name": "bug", "template_data": {}}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_guest_can_list_but_not_create(self, workspace, project):
        WorkItemTemplate.objects.create(name="Bug", project=project)
        guest = client_for(workspace, project, "guest@plane.so", 5)

        assert [t["name"] for t in guest.get(url(workspace, project)).data] == ["Bug"]
        response = guest.post(url(workspace, project), {"name": "Mine", "template_data": {}}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_member_updates_any_but_deletes_only_own(self, workspace, project):
        others = WorkItemTemplate.objects.create(name="Admin's", project=project)
        member = client_for(workspace, project, "member@plane.so", 15)

        response = member.patch(url(workspace, project, others.id), {"name": "Renamed"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert member.delete(url(workspace, project, others.id)).status_code == status.HTTP_403_FORBIDDEN

        own = member.post(url(workspace, project), {"name": "Mine", "template_data": {}}, format="json").data
        assert member.delete(url(workspace, project, own["id"])).status_code == status.HTTP_204_NO_CONTENT
        assert list(WorkItemTemplate.objects.values_list("name", flat=True)) == ["Renamed"]

    @pytest.mark.django_db
    def test_other_projects_templates_are_not_reachable(self, session_client, workspace, project, create_user):
        other = Project.objects.create(name="Other", identifier="OTH", workspace=workspace, created_by=create_user)
        template = WorkItemTemplate.objects.create(name="Elsewhere", project=other)

        response = session_client.patch(url(workspace, project, template.id), {"name": "x"}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND
