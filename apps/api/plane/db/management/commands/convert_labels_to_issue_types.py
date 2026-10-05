# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.core.management import BaseCommand, CommandError
from django.db import transaction

# Module imports
from plane.db.models import Issue, IssueLabel, Label, Project
from plane.utils.issue_types import (
    create_project_issue_type,
    default_logo_for,
    mark_default_issue_type,
    project_issue_types,
)

# When a work item carries several of these labels the first one listed wins.
DEFAULT_TYPE_LABELS = ["Epic", "Sub-task", "Bug", "Story", "Improvement", "New Feature", "Task"]


class Command(BaseCommand):
    help = (
        "Turn type-like labels (Bug, Task, Story, ...) of a project into work item types: creates a type per label, "
        "sets it on the work items carrying the label, and switches work item types on for the project."
    )

    def add_arguments(self, parser):
        parser.add_argument("workspace_slug", type=str)
        parser.add_argument("project_identifier", type=str)
        parser.add_argument(
            "--labels",
            type=str,
            default=",".join(DEFAULT_TYPE_LABELS),
            help="Comma separated label names to convert, most specific first",
        )
        parser.add_argument("--default", type=str, default="Task", help="Type new work items get by default")
        parser.add_argument(
            "--type-untyped",
            action="store_true",
            help="Also give the default type to work items that carry none of the labels",
        )
        parser.add_argument(
            "--remove-labels",
            action="store_true",
            help="Remove the converted labels from the project once the types are set",
        )
        parser.add_argument("--dry-run", action="store_true", help="Report what would change, change nothing")

    def handle(self, *args, **options):
        project = Project.objects.filter(
            workspace__slug=options["workspace_slug"], identifier=options["project_identifier"]
        ).first()
        if not project:
            raise CommandError("Project not found")

        dry_run = options["dry_run"]
        names = [name.strip() for name in options["labels"].split(",") if name.strip()]

        with transaction.atomic():
            existing_types = {issue_type.name.lower(): issue_type for issue_type in project_issue_types(project.id)}
            converted_labels = []

            for name in names:
                label = Label.objects.filter(project=project, name__iexact=name).first()
                if not label:
                    self.stdout.write(f"- {name}: no such label, skipped")
                    continue

                issue_type = existing_types.get(name.lower())
                if not issue_type:
                    issue_type = create_project_issue_type(
                        project,
                        name=label.name,
                        logo_props=default_logo_for(label.name),
                        is_epic=label.name.lower() == "epic",
                    )
                    existing_types[name.lower()] = issue_type

                updated = Issue.objects.filter(
                    project=project,
                    type__isnull=True,
                    label_issue__label_id=label.id,
                    label_issue__deleted_at__isnull=True,
                ).update(type=issue_type)
                converted_labels.append(label)
                self.stdout.write(f"- {label.name}: {updated} work items")

            default_type = existing_types.get(options["default"].lower()) or next(iter(existing_types.values()), None)
            if not default_type:
                raise CommandError("None of the labels exist in this project, nothing to convert")
            mark_default_issue_type(project.id, default_type.id)
            self.stdout.write(f"Default type: {default_type.name}")

            untyped = Issue.objects.filter(project=project, type__isnull=True)
            if options["type_untyped"]:
                self.stdout.write(
                    f"- (no type label) -> {default_type.name}: {untyped.update(type=default_type)} work items"
                )
            else:
                self.stdout.write(f"Work items left without a type: {untyped.count()}")

            if options["remove_labels"]:
                label_ids = [label.id for label in converted_labels]
                removed = IssueLabel.objects.filter(label_id__in=label_ids).count()
                IssueLabel.objects.filter(label_id__in=label_ids).delete()
                Label.objects.filter(id__in=label_ids).delete()
                self.stdout.write(f"Removed {len(label_ids)} labels ({removed} label assignments)")

            Project.objects.filter(pk=project.id).update(is_issue_type_enabled=True)

            if dry_run:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Dry run: nothing was changed"))
            else:
                self.stdout.write(self.style.SUCCESS("Work item types are on for this project"))
