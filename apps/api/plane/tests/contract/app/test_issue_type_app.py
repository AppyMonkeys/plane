# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json

import pytest
from django.core.management import call_command
from rest_framework import status

from plane.celery import app as celery_app
from plane.db.models import (
    Issue,
    IssueActivity,
    IssueLabel,
    IssueType,
    Label,
    Project,
    ProjectMember,
    State,
)
from plane.utils.issue_types import DEFAULT_ISSUE_TYPES, create_project_issue_type, project_issue_types


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
    project = Project.objects.create(name="Test Project", identifier="TP", workspace=workspace, created_by=create_user)
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
def typed_project(session_client, workspace, project):
    """A project with work item types switched on (which seeds the default set)."""
    response = session_client.patch(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/", {"is_issue_type_enabled": True}, format="json"
    )
    assert response.status_code == status.HTTP_200_OK
    return project


def types_url(workspace, project):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/issue-types/"


def issues_url(workspace, project):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/"


@pytest.mark.contract
class TestIssueTypeAppContract:
    @pytest.mark.django_db
    def test_enabling_types_seeds_the_default_set(self, session_client, workspace, typed_project):
        response = session_client.get(types_url(workspace, typed_project))

        assert response.status_code == status.HTTP_200_OK
        assert [issue_type["name"] for issue_type in response.data] == [t["name"] for t in DEFAULT_ISSUE_TYPES]
        assert [t["name"] for t in response.data if t["is_default"]] == ["Task"]
        assert response.data[0]["project_ids"] == [str(typed_project.id)]

    @pytest.mark.django_db
    def test_enabling_twice_does_not_duplicate_types(self, session_client, workspace, typed_project):
        url = f"/api/workspaces/{workspace.slug}/projects/{typed_project.id}/"
        session_client.patch(url, {"is_issue_type_enabled": False}, format="json")
        session_client.patch(url, {"is_issue_type_enabled": True}, format="json")

        assert project_issue_types(typed_project.id).count() == len(DEFAULT_ISSUE_TYPES)

    @pytest.mark.django_db
    def test_create_rejects_a_duplicate_name(self, session_client, workspace, typed_project):
        created = session_client.post(types_url(workspace, typed_project), {"name": "Spike"}, format="json")
        duplicate = session_client.post(types_url(workspace, typed_project), {"name": "spike"}, format="json")

        assert created.status_code == status.HTTP_201_CREATED
        assert created.data["logo_props"]["icon"]["name"]
        assert created.data["is_default"] is False
        assert duplicate.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_mark_default_moves_the_default(self, session_client, workspace, typed_project):
        bug = project_issue_types(typed_project.id).get(name="Bug")

        response = session_client.post(f"{types_url(workspace, typed_project)}{bug.id}/mark-default/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert list(project_issue_types(typed_project.id).filter(is_default=True).values_list("name", flat=True)) == [
            "Bug"
        ]

    @pytest.mark.django_db
    def test_default_and_in_use_types_cannot_be_deleted(self, session_client, workspace, typed_project):
        task = project_issue_types(typed_project.id).get(name="Task")
        bug = project_issue_types(typed_project.id).get(name="Bug")
        story = project_issue_types(typed_project.id).get(name="Story")
        Issue.objects.create(name="Crash", project=typed_project, workspace=workspace, type=bug)

        url = types_url(workspace, typed_project)
        assert session_client.delete(f"{url}{task.id}/").status_code == status.HTTP_400_BAD_REQUEST
        assert session_client.delete(f"{url}{bug.id}/").status_code == status.HTTP_400_BAD_REQUEST
        assert session_client.delete(f"{url}{story.id}/").status_code == status.HTTP_204_NO_CONTENT
        assert not project_issue_types(typed_project.id).filter(name="Story").exists()

    @pytest.mark.django_db
    def test_new_work_item_gets_the_default_type(self, session_client, workspace, typed_project):
        response = session_client.post(issues_url(workspace, typed_project), {"name": "Write docs"}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        task = project_issue_types(typed_project.id).get(name="Task")
        assert str(response.data["type_id"]) == str(task.id)

    @pytest.mark.django_db
    def test_new_work_item_has_no_type_when_types_are_off(self, session_client, workspace, project):
        response = session_client.post(issues_url(workspace, project), {"name": "Write docs"}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["type_id"] is None

    @pytest.mark.django_db
    def test_type_can_be_changed_and_is_logged(self, session_client, workspace, typed_project):
        created = session_client.post(issues_url(workspace, typed_project), {"name": "Crash"}, format="json")
        bug = project_issue_types(typed_project.id).get(name="Bug")
        issue_url = f"{issues_url(workspace, typed_project)}{created.data['id']}/"

        response = session_client.patch(issue_url, {"type_id": str(bug.id)}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert Issue.objects.get(pk=created.data["id"]).type_id == bug.id
        activity = IssueActivity.objects.get(issue_id=created.data["id"], field="type")
        assert (activity.old_value, activity.new_value) == ("Task", "Bug")
        # and the list endpoint hands the type back to the app
        listed = session_client.get(issues_url(workspace, typed_project))
        assert str(listed.data["results"][0]["type_id"]) == str(bug.id)

    @pytest.mark.django_db
    def test_work_items_can_be_filtered_by_type(self, session_client, workspace, typed_project):
        bug = project_issue_types(typed_project.id).get(name="Bug")
        story = project_issue_types(typed_project.id).get(name="Story")
        Issue.objects.create(name="Crash", project=typed_project, workspace=workspace, type=bug)
        Issue.objects.create(name="Login", project=typed_project, workspace=workspace, type=story)
        Issue.objects.create(name="Untyped", project=typed_project, workspace=workspace)

        def names(filters):
            response = session_client.get(issues_url(workspace, typed_project), {"filters": json.dumps(filters)})
            assert response.status_code == status.HTTP_200_OK
            return sorted(issue["name"] for issue in response.data["results"])

        assert names({"and": [{"type_id__in": f"{bug.id},{story.id}"}]}) == ["Crash", "Login"]
        assert names({"and": [{"type_id": str(bug.id)}]}) == ["Crash"]
        assert names({"and": [{"not": {"type_id__in": str(bug.id)}}]}) == ["Login", "Untyped"]

    @pytest.mark.django_db
    def test_type_from_another_project_is_rejected(self, session_client, workspace, typed_project, create_user):
        other = Project.objects.create(name="Other", identifier="OT", workspace=workspace, created_by=create_user)
        foreign_type = IssueType.objects.create(workspace=workspace, name="Foreign")
        other.project_projectissuetype.create(issue_type=foreign_type, workspace=workspace)

        response = session_client.post(
            issues_url(workspace, typed_project), {"name": "Nope", "type_id": str(foreign_type.id)}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_workspace_endpoint_lists_types_of_my_projects(self, session_client, workspace, typed_project):
        response = session_client.get(f"/api/workspaces/{workspace.slug}/issue-types/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == len(DEFAULT_ISSUE_TYPES)


@pytest.mark.contract
class TestWorkItemTypesOnByDefault:
    @pytest.mark.django_db
    def test_new_project_has_types_on_with_the_default_set(self, session_client, workspace):
        response = session_client.post(
            f"/api/workspaces/{workspace.slug}/projects/", {"name": "Fresh", "identifier": "FRESH"}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["is_issue_type_enabled"] is True
        types = project_issue_types(response.data["id"])
        assert [t.name for t in types] == [t["name"] for t in DEFAULT_ISSUE_TYPES]
        assert [t.name for t in types if t.is_default] == ["Task"]

    @pytest.mark.django_db
    def test_enable_command_switches_every_project_on_and_fills_gaps(self, workspace, project, create_user):
        # one project already has a hand-made set with its own default, the other has nothing
        custom = Project.objects.create(name="Custom", identifier="CUS", workspace=workspace, created_by=create_user)
        spike = create_project_issue_type(custom, name="Spike", is_default=True)
        create_project_issue_type(custom, name="bug")
        typed = Issue.objects.create(name="Keep me", project=custom, workspace=workspace, type=spike)

        call_command("enable_issue_types")
        call_command("enable_issue_types")  # running it again changes nothing

        assert Project.objects.get(pk=project.id).is_issue_type_enabled is True
        assert [t.name for t in project_issue_types(project.id)] == [t["name"] for t in DEFAULT_ISSUE_TYPES]
        custom_types = [t.name for t in project_issue_types(custom.id)]
        assert sorted(name.lower() for name in custom_types) == sorted(
            ["spike"] + [t["name"].lower() for t in DEFAULT_ISSUE_TYPES]
        )
        assert [t.name for t in project_issue_types(custom.id) if t.is_default] == ["Spike"]
        assert Issue.objects.get(pk=typed.id).type_id == spike.id


@pytest.mark.contract
class TestParentPickerOffersEpics:
    def search(self, client, workspace, project, **params):
        response = client.get(
            f"/api/workspaces/{workspace.slug}/projects/{project.id}/search-issues/",
            {"workspace_search": "false", **params},
        )
        assert response.status_code == status.HTTP_200_OK
        return sorted(issue["name"] for issue in response.data)

    @pytest.mark.django_db
    def test_only_epics_are_offered_as_parent(self, session_client, workspace, typed_project):
        types = {t.name: t for t in project_issue_types(typed_project.id)}
        Issue.objects.create(name="Big epic", project=typed_project, workspace=workspace, type=types["Epic"])
        Issue.objects.create(name="Other epic", project=typed_project, workspace=workspace, type=types["Epic"])
        child = Issue.objects.create(name="A task", project=typed_project, workspace=workspace, type=types["Task"])
        Issue.objects.create(name="A bug", project=typed_project, workspace=workspace, type=types["Bug"])

        # from a ticket page, and from the create dialog (no ticket yet)
        assert self.search(session_client, workspace, typed_project, parent="true", issue_id=str(child.id)) == [
            "Big epic",
            "Other epic",
        ]
        assert self.search(session_client, workspace, typed_project, parent="true") == ["Big epic", "Other epic"]
        # other pickers (e.g. relations) still see everything
        assert len(self.search(session_client, workspace, typed_project)) == 4

    @pytest.mark.django_db
    def test_projects_without_types_offer_every_work_item(self, session_client, workspace, project):
        Issue.objects.create(name="One", project=project, workspace=workspace)
        Issue.objects.create(name="Two", project=project, workspace=workspace)

        assert self.search(session_client, workspace, project, parent="true") == ["One", "Two"]


@pytest.mark.contract
class TestConvertLabelsToIssueTypes:
    @pytest.mark.django_db
    def test_labels_become_types(self, workspace, project):
        bug_label = Label.objects.create(name="Bug", project=project, workspace=workspace)
        task_label = Label.objects.create(name="Task", project=project, workspace=workspace)
        Label.objects.create(name="frontend", project=project, workspace=workspace)
        crash = Issue.objects.create(name="Crash", project=project, workspace=workspace)
        chore = Issue.objects.create(name="Chore", project=project, workspace=workspace)
        both = Issue.objects.create(name="Both", project=project, workspace=workspace)
        untouched = Issue.objects.create(name="No label", project=project, workspace=workspace)
        IssueLabel.objects.create(issue=crash, label=bug_label, project=project, workspace=workspace)
        IssueLabel.objects.create(issue=chore, label=task_label, project=project, workspace=workspace)
        IssueLabel.objects.create(issue=both, label=bug_label, project=project, workspace=workspace)
        IssueLabel.objects.create(issue=both, label=task_label, project=project, workspace=workspace)

        call_command("convert_labels_to_issue_types", workspace.slug, project.identifier)

        types = {t.name: t for t in project_issue_types(project.id)}
        assert set(types) == {"Bug", "Task"}
        assert types["Task"].is_default is True
        assert Issue.objects.get(pk=crash.id).type_id == types["Bug"].id
        assert Issue.objects.get(pk=chore.id).type_id == types["Task"].id
        # Bug is listed before Task, so it wins when both labels are present
        assert Issue.objects.get(pk=both.id).type_id == types["Bug"].id
        assert Issue.objects.get(pk=untouched.id).type_id is None
        assert Project.objects.get(pk=project.id).is_issue_type_enabled is True
        # labels stay unless asked otherwise
        assert Label.objects.filter(project=project).count() == 3

    @pytest.mark.django_db
    def test_dry_run_changes_nothing(self, workspace, project):
        label = Label.objects.create(name="Bug", project=project, workspace=workspace)
        crash = Issue.objects.create(name="Crash", project=project, workspace=workspace)
        IssueLabel.objects.create(issue=crash, label=label, project=project, workspace=workspace)

        call_command("convert_labels_to_issue_types", workspace.slug, project.identifier, "--dry-run")

        assert not project_issue_types(project.id).exists()
        assert Issue.objects.get(pk=crash.id).type_id is None
        assert Project.objects.get(pk=project.id).is_issue_type_enabled is False


@pytest.mark.contract
class TestIssueTypePublicApiContract:
    @pytest.mark.django_db
    def test_list_and_create_types(self, api_key_client, workspace, project):
        url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-item-types/"

        created = api_key_client.post(url, {"name": "Bug"}, format="json")
        duplicate = api_key_client.post(url, {"name": "bug"}, format="json")
        listed = api_key_client.get(url)

        assert created.status_code == status.HTTP_201_CREATED
        assert created.data["is_default"] is True
        assert duplicate.status_code == status.HTTP_409_CONFLICT
        assert str(duplicate.data["id"]) == str(created.data["id"])
        assert [t["name"] for t in listed.data] == ["Bug"]
