# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import serializers

# Module imports
from .base import BaseSerializer
from plane.db.models import WorkItemTemplate

# The work item fields a template can fill in. Anything else sent in template_data is dropped.
TEMPLATE_FIELDS = {
    "name": str,
    "description_html": str,
    "type_id": str,
    "priority": str,
    "state_id": str,
    "label_ids": list,
    "assignee_ids": list,
    "module_ids": list,
}


class WorkItemTemplateSerializer(BaseSerializer):
    class Meta:
        model = WorkItemTemplate
        fields = [
            "id",
            "name",
            "template_data",
            "project_id",
            "workspace_id",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["project_id", "workspace_id", "created_by", "created_at", "updated_at"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Give the template a name")
        return value

    def validate_template_data(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Must be an object of work item fields")
        cleaned = {}
        for field, kind in TEMPLATE_FIELDS.items():
            if value.get(field) is None:
                continue
            is_valid = isinstance(value[field], kind) and (
                kind is not list or all(isinstance(item, str) for item in value[field])
            )
            if not is_valid:
                raise serializers.ValidationError({field: f"Must be a {'list of ids' if kind is list else 'string'}"})
            cleaned[field] = value[field]
        return cleaned
