# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import base64
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from plane.celery import app as celery_app
from plane.db.models import (
    Issue,
    IssueActivity,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    Label,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)
from plane.utils.issue_types import create_project_issue_type

BASE = "/api/jira/rest/api/2"
TICKET_FIELDS = "summary,status,priority,issuetype,assignee,description,updated,comment,duedate,labels"


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
        name="Lokko", identifier="LOKKO", workspace=workspace, created_by=create_user, is_issue_type_enabled=True
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    for sequence, (name, group) in enumerate(
        [
            ("Backlog", "backlog"),
            ("Todo", "unstarted"),
            ("In Progress", "started"),
            ("In Review", "started"),
            ("Done", "completed"),
        ]
    ):
        State.objects.create(
            name=name, group=group, color="#000000", sequence=sequence * 1000, project=project, workspace=workspace
        )
    return project


@pytest.fixture
def teammate(db, workspace, project):
    user = User.objects.create(email="teammate@plane.so", username="teammate", first_name="Team", last_name="Mate")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15, is_active=True)
    ProjectMember.objects.create(project=project, member=user, role=15, is_active=True)
    return user


@pytest.fixture
def tickets(db, workspace, project, create_user, teammate):
    """Three tickets: two of mine (a To Do bug, an In Progress task), one of my teammate's."""
    states = {state.name: state for state in State.objects.filter(project=project)}
    bug = create_project_issue_type(project, name="Bug", is_default=False)
    task = create_project_issue_type(project, name="Task", is_default=True)
    bug_label = Label.objects.create(name="Bug", project=project, workspace=workspace)
    ui_label = Label.objects.create(name="ui", project=project, workspace=workspace)

    def make(name, state, issue_type, priority, assignee, description=""):
        issue = Issue.objects.create(
            name=name,
            project=project,
            workspace=workspace,
            state=states[state],
            type=issue_type,
            priority=priority,
            description_html=f"<p>{description}</p>",
            created_by=create_user,
        )
        IssueAssignee.objects.create(issue=issue, assignee=assignee, project=project, workspace=workspace)
        return issue

    crash = make("Crash on login", "Todo", bug, "urgent", create_user, "The piranha eats the save file")
    chore = make("Tidy the build", "In Progress", task, "low", create_user)
    other = make("Someone else's ticket", "Todo", task, "medium", teammate)
    IssueLabel.objects.create(issue=crash, label=bug_label, project=project, workspace=workspace)
    IssueLabel.objects.create(issue=crash, label=ui_label, project=project, workspace=workspace)
    IssueComment.objects.create(
        issue=crash, project=project, workspace=workspace, actor=teammate, comment_html="<p>Seen on octopus level</p>"
    )
    return {"crash": crash, "chore": chore, "other": other}


@pytest.fixture
def jira_client(create_user, api_token):
    """A client authenticating the way the Jira tool does: Basic email:api-token."""
    client = APIClient()
    credentials = base64.b64encode(f"{create_user.email}:{api_token.token}".encode()).decode()
    client.credentials(HTTP_AUTHORIZATION=f"Basic {credentials}")
    return client


def search(client, jql, **params):
    return client.get(f"{BASE}/search/jql", {"jql": jql, "maxResults": 100, "fields": TICKET_FIELDS, **params})


def keys(response):
    return [issue["key"] for issue in response.data["issues"]]


@pytest.mark.contract
class TestJiraCompatAuth:
    @pytest.mark.django_db
    def test_myself_returns_the_account_id(self, jira_client, create_user):
        response = jira_client.get(f"{BASE}/myself")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["accountId"] == str(create_user.id)

    @pytest.mark.django_db
    def test_requests_without_credentials_are_rejected(self, db):
        assert APIClient().get(f"{BASE}/myself").status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.django_db
    def test_token_with_someone_elses_email_is_rejected(self, api_token):
        client = APIClient()
        credentials = base64.b64encode(f"other@plane.so:{api_token.token}".encode()).decode()
        client.credentials(HTTP_AUTHORIZATION=f"Basic {credentials}")

        assert client.get(f"{BASE}/myself").status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.contract
class TestJiraCompatSearch:
    @pytest.mark.django_db
    def test_my_tickets_come_back_in_jira_shape(self, jira_client, tickets, create_user):
        response = search(jira_client, 'project = "LOKKO" AND assignee = currentUser() ORDER BY updated DESC')

        assert response.status_code == status.HTTP_200_OK
        assert sorted(keys(response)) == ["LOKKO-1", "LOKKO-2"]
        assert response.data["isLast"] is True
        crash = next(issue for issue in response.data["issues"] if issue["key"] == "LOKKO-1")["fields"]
        assert crash["summary"] == "Crash on login"
        assert crash["status"]["name"] == "To Do"  # Plane's "Todo", in Jira's words
        assert crash["priority"]["name"] == "Highest"
        assert crash["issuetype"]["name"] == "Bug"
        assert crash["assignee"]["accountId"] == str(create_user.id)
        assert crash["description"] == "The piranha eats the save file"
        assert crash["labels"] == ["ui"]  # the "Bug" label duplicates the type and is left out
        assert [comment["body"] for comment in crash["comment"]["comments"]] == ["Seen on octopus level"]
        assert crash["comment"]["comments"][0]["author"]["displayName"] == "Team Mate"

    @pytest.mark.django_db
    def test_status_priority_and_type_filters(self, jira_client, tickets):
        mine = 'project = "LOKKO" AND assignee = currentUser()'

        assert keys(search(jira_client, f'{mine} AND status IN ("To Do", "Done")')) == ["LOKKO-1"]
        assert keys(search(jira_client, f'{mine} AND priority IN ("Low", "Lowest")')) == ["LOKKO-2"]
        assert keys(search(jira_client, f'{mine} AND issuetype IN ("Bug")')) == ["LOKKO-1"]
        assert keys(search(jira_client, f'{mine} AND status IN ("Reopened")')) == []

    @pytest.mark.django_db
    def test_updated_since_returns_everyones_recent_changes(self, jira_client, tickets):
        Issue.objects.filter(pk=tickets["chore"].id).update(updated_at=timezone.now() - timedelta(hours=3))

        response = search(jira_client, 'project = "LOKKO" AND updated >= -32m ORDER BY updated DESC')

        assert sorted(keys(response)) == ["LOKKO-1", "LOKKO-3"]

    @pytest.mark.django_db
    def test_text_search_covers_title_description_and_comments(self, jira_client, tickets):
        def find(terms):
            return keys(search(jira_client, f'project = "LOKKO" AND text ~ "{terms}" ORDER BY updated DESC'))

        assert find("login") == ["LOKKO-1"]
        assert find("piranha save") == ["LOKKO-1"]
        assert find("octopus") == ["LOKKO-1"]
        assert find("piranha unicorn") == []

    @pytest.mark.django_db
    def test_paging_follows_next_page_token(self, jira_client, tickets):
        jql = 'project = "LOKKO" ORDER BY key ASC'

        first = search(jira_client, jql, maxResults=2)
        second = search(jira_client, jql, maxResults=2, nextPageToken=first.data["nextPageToken"])

        assert keys(first) == ["LOKKO-1", "LOKKO-2"] and first.data["isLast"] is False
        assert first.data["total"] == 3
        assert keys(second) == ["LOKKO-3"] and second.data["isLast"] is True
        assert "nextPageToken" not in second.data

    @pytest.mark.django_db
    def test_unsupported_jql_is_a_400_with_jira_errors(self, jira_client, tickets):
        response = search(jira_client, 'project = "LOKKO" OR sprint = 4')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["errorMessages"]

    @pytest.mark.django_db
    def test_projects_i_am_not_in_are_invisible(self, jira_client, tickets, workspace, teammate):
        secret = Project.objects.create(name="Secret", identifier="SEC", workspace=workspace, created_by=teammate)
        ProjectMember.objects.create(project=secret, member=teammate, role=20, is_active=True)
        Issue.objects.create(name="Hidden", project=secret, workspace=workspace)

        assert keys(search(jira_client, 'project = "SEC"')) == []
        assert jira_client.get(f"{BASE}/issue/SEC-1").status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.contract
class TestJiraCompatIssue:
    @pytest.mark.django_db
    def test_issue_by_key(self, jira_client, tickets):
        response = jira_client.get(f"{BASE}/issue/LOKKO-2", {"fields": TICKET_FIELDS})

        assert response.status_code == status.HTTP_200_OK
        assert response.data["key"] == "LOKKO-2"
        assert response.data["fields"]["status"]["name"] == "In Progress"

    @pytest.mark.django_db
    def test_unknown_key_is_a_404(self, jira_client, tickets):
        assert jira_client.get(f"{BASE}/issue/LOKKO-999").status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_stock_transition_ids_move_the_ticket(self, jira_client, tickets):
        url = "/api/jira/rest/api/3/issue/LOKKO-1/transitions"

        response = jira_client.post(url, {"transition": {"id": "31"}}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert Issue.objects.get(pk=tickets["crash"].id).state.name == "In Review"
        assert IssueActivity.objects.filter(issue=tickets["crash"], field="state", new_value="In Review").exists()
        assert jira_client.post(url, {"transition": {"id": "999"}}, format="json").status_code == 400

    @pytest.mark.django_db
    def test_transitions_list_offers_every_other_state(self, jira_client, tickets):
        response = jira_client.get(f"{BASE}/issue/LOKKO-1/transitions")

        assert [t["name"] for t in response.data["transitions"]] == ["Backlog", "In Progress", "In Review", "Done"]

    @pytest.mark.django_db
    def test_comment_is_posted_as_the_caller(self, jira_client, tickets, create_user):
        response = jira_client.post(
            f"{BASE}/issue/LOKKO-2/comment", {"body": "Fixed in <build 42>\nplease verify"}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        comment = IssueComment.objects.get(issue=tickets["chore"])
        assert comment.actor_id == create_user.id and comment.created_by_id == create_user.id
        assert comment.comment_html == "<p>Fixed in &lt;build 42&gt;</p><p>please verify</p>"

    @pytest.mark.django_db
    def test_browse_link_redirects_to_the_web_app(self, tickets, workspace):
        response = APIClient().get("/api/jira/browse/LOKKO-1")

        assert response.status_code == status.HTTP_302_FOUND
        assert response["Location"] == f"/{workspace.slug}/browse/LOKKO-1/"


@pytest.mark.contract
class TestWorkItemListFilters:
    """The public work item list accepts the same filters as the web app."""

    def url(self, workspace, project):
        return f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/"

    def names(self, response):
        assert response.status_code == status.HTTP_200_OK, response.data
        return sorted(issue["name"] for issue in response.data["results"])

    @pytest.mark.django_db
    def test_flat_filter_parameters(self, api_key_client, workspace, project, tickets):
        url = self.url(workspace, project)
        todo = State.objects.get(project=project, name="Todo")

        assert self.names(api_key_client.get(url, {"assignee_id": "me"})) == ["Crash on login", "Tidy the build"]
        assert self.names(api_key_client.get(url, {"assignee_id": "me", "state_id__in": str(todo.id)})) == [
            "Crash on login"
        ]
        assert self.names(api_key_client.get(url, {"priority__in": "low,medium"})) == [
            "Someone else's ticket",
            "Tidy the build",
        ]
        assert self.names(api_key_client.get(url, {"type_id": str(tickets["crash"].type_id)})) == ["Crash on login"]

    @pytest.mark.django_db
    def test_updated_since(self, api_key_client, workspace, project, tickets):
        Issue.objects.filter(pk=tickets["chore"].id).update(updated_at=timezone.now() - timedelta(hours=3))
        since = (timezone.now() - timedelta(minutes=30)).isoformat()

        response = api_key_client.get(self.url(workspace, project), {"updated_at__gte": since})

        assert self.names(response) == ["Crash on login", "Someone else's ticket"]
        assert response.data["total_results"] == 2

    @pytest.mark.django_db
    def test_json_filters(self, api_key_client, workspace, project, tickets):
        filters = '{"and": [{"priority__in": "urgent,low"}, {"not": {"state_group": "started"}}]}'

        assert self.names(api_key_client.get(self.url(workspace, project), {"filters": filters})) == ["Crash on login"]

    @pytest.mark.django_db
    def test_unknown_filter_field_is_rejected(self, api_key_client, workspace, project, tickets):
        response = api_key_client.get(self.url(workspace, project), {"filters": '{"and": [{"name": "x"}]}'})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
