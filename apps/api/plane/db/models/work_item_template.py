# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import models
from django.db.models import Q

# Module imports
from .project import ProjectBaseModel


class WorkItemTemplate(ProjectBaseModel):
    """A saved set of work item fields that anyone in the project can start a new work item from."""

    name = models.CharField(max_length=255)
    # the work item fields to fill in, as the create form sends them (name, description_html, type_id, ...)
    template_data = models.JSONField(default=dict)

    class Meta:
        verbose_name = "Work Item Template"
        verbose_name_plural = "Work Item Templates"
        db_table = "work_item_templates"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["project", "name"],
                condition=Q(deleted_at__isnull=True),
                name="work_item_template_unique_project_name_when_deleted_at_null",
            )
        ]

    def __str__(self):
        return f"{self.name} <{self.project_id}>"
