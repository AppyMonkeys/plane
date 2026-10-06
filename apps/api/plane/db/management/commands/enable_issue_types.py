# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.core.management import BaseCommand

# Module imports
from plane.db.models import Project
from plane.utils.issue_types import enable_issue_types, project_issue_types


class Command(BaseCommand):
    help = (
        "Switch work item types on for every project (or one workspace's projects) and add any of the "
        "default types a project is missing. Existing types and work items are left as they are."
    )

    def add_arguments(self, parser):
        parser.add_argument("--workspace", type=str, help="Only this workspace (slug)")

    def handle(self, *args, **options):
        projects = Project.objects.filter(archived_at__isnull=True).select_related("workspace")
        if options.get("workspace"):
            projects = projects.filter(workspace__slug=options["workspace"])

        for project in projects.order_by("workspace__slug", "identifier"):
            was_enabled = project.is_issue_type_enabled
            added = enable_issue_types(project)
            names = ", ".join(project_issue_types(project.id).values_list("name", flat=True))
            self.stdout.write(
                f"{project.workspace.slug}/{project.identifier}: "
                f"{'already on' if was_enabled else 'switched on'}; "
                f"added {[issue_type.name for issue_type in added] or 'nothing'}; types now: {names}"
            )
        self.stdout.write(self.style.SUCCESS("Done"))
