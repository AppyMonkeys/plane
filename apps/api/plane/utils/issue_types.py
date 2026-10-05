# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import transaction

# Module imports
from plane.db.models import IssueType, ProjectIssueType


def type_logo(icon, background_color):
    return {
        "in_use": "icon",
        "icon": {"name": icon, "color": "#ffffff", "background_color": background_color},
    }


# The work item types a project starts with -- the same set Jira ships with.
DEFAULT_ISSUE_TYPES = [
    {
        "name": "Task",
        "description": "A small, distinct piece of work.",
        "logo_props": type_logo("Check", "#4bade8"),
        "is_default": True,
    },
    {
        "name": "Bug",
        "description": "A problem or error.",
        "logo_props": type_logo("Bug", "#e5493a"),
    },
    {
        "name": "Story",
        "description": "Functionality or a feature expressed as a user goal.",
        "logo_props": type_logo("Bookmark", "#63ba3c"),
    },
    {
        "name": "Epic",
        "description": "A big user story that needs to be broken down.",
        "logo_props": type_logo("Zap", "#904ee2"),
        "is_epic": True,
    },
    {
        "name": "Sub-task",
        "description": "A small piece of work that's part of a larger task.",
        "logo_props": type_logo("ListTree", "#4bade8"),
    },
]

# Looks for other names that commonly come over from Jira.
EXTRA_ISSUE_TYPE_LOGOS = {
    "improvement": type_logo("TrendingUp", "#63ba3c"),
    "new feature": type_logo("Plus", "#63ba3c"),
    "feature": type_logo("Plus", "#63ba3c"),
    "subtask": type_logo("ListTree", "#4bade8"),
}

FALLBACK_ISSUE_TYPE_LOGO = type_logo("Circle", "#6b7280")


def default_logo_for(name):
    """Logo for a type name: the built-in look when we know the name, a neutral one otherwise."""
    key = (name or "").strip().lower()
    for issue_type in DEFAULT_ISSUE_TYPES:
        if issue_type["name"].lower() == key:
            return issue_type["logo_props"]
    return EXTRA_ISSUE_TYPE_LOGOS.get(key, FALLBACK_ISSUE_TYPE_LOGO)


def project_issue_types(project_id):
    """Work item types of a project, in display order."""
    return (
        IssueType.objects.filter(
            project_issue_types__project_id=project_id,
            project_issue_types__deleted_at__isnull=True,
        )
        .distinct()
        .order_by("level", "created_at")
    )


def get_default_issue_type(project_id):
    return project_issue_types(project_id).filter(is_default=True, is_active=True).first()


@transaction.atomic
def create_project_issue_type(project, **fields):
    """Create a work item type and attach it to the project."""
    level = fields.pop("level", None)
    if level is None:
        last = project_issue_types(project.id).order_by("-level").first()
        level = (last.level + 1) if last else 0

    issue_type = IssueType.objects.create(
        workspace_id=project.workspace_id,
        level=level,
        **fields,
    )
    ProjectIssueType.objects.create(
        project=project,
        workspace_id=project.workspace_id,
        issue_type=issue_type,
        level=int(level),
        is_default=issue_type.is_default,
    )
    return issue_type


def seed_default_issue_types(project):
    """Give a project the default set of types, unless it already has some."""
    if project_issue_types(project.id).exists():
        return []
    return [
        create_project_issue_type(project, level=index, **issue_type)
        for index, issue_type in enumerate(DEFAULT_ISSUE_TYPES)
    ]


def mark_default_issue_type(project_id, issue_type_id):
    """Make one type the project's default (the type new work items get)."""
    type_ids = list(project_issue_types(project_id).values_list("id", flat=True))
    IssueType.objects.filter(id__in=type_ids).exclude(id=issue_type_id).update(is_default=False)
    IssueType.objects.filter(id=issue_type_id, id__in=type_ids).update(is_default=True)
    ProjectIssueType.objects.filter(project_id=project_id).exclude(issue_type_id=issue_type_id).update(is_default=False)
    ProjectIssueType.objects.filter(project_id=project_id, issue_type_id=issue_type_id).update(is_default=True)
