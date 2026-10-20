# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.core.management import BaseCommand
from django.template.defaultfilters import slugify

# Module imports
from plane.db.models import DEFAULT_STATES, Project, State


def add_missing_default_states(project):
    """Add the default states a project doesn't have yet, matched by name (any case). Returns the new states.

    Existing states are never changed, and no added state becomes the project default.
    """
    # all_state_objects includes triage states; soft-deleted ones don't count
    existing = {
        name.lower()
        for name in State.all_state_objects.filter(project=project, deleted_at__isnull=True).values_list(
            "name", flat=True
        )
    }
    missing = [state for state in DEFAULT_STATES if state["name"].lower() not in existing]
    return State.objects.bulk_create(
        [
            State(
                name=state["name"],
                slug=slugify(state["name"]),
                color=state["color"],
                project=project,
                workspace_id=project.workspace_id,
                sequence=state["sequence"],
                group=state["group"],
                default=False,
            )
            for state in missing
        ]
    )


class Command(BaseCommand):
    help = (
        "Add the default states (e.g. Reopened, Duplicate) to every project that is missing them. "
        "Existing states and work items are left as they are."
    )

    def add_arguments(self, parser):
        parser.add_argument("--workspace", type=str, help="Only this workspace (slug)")

    def handle(self, *args, **options):
        projects = Project.objects.filter(archived_at__isnull=True).select_related("workspace")
        if options.get("workspace"):
            projects = projects.filter(workspace__slug=options["workspace"])

        for project in projects.order_by("workspace__slug", "identifier"):
            added = add_missing_default_states(project)
            self.stdout.write(
                f"{project.workspace.slug}/{project.identifier}: added {[state.name for state in added] or 'nothing'}"
            )
        self.stdout.write(self.style.SUCCESS("Done"))
