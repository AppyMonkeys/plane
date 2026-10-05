# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import serializers

# Module imports
from .base import BaseSerializer
from plane.db.models import IssueType


class IssueTypeSerializer(BaseSerializer):
    project_ids = serializers.SerializerMethodField()

    class Meta:
        model = IssueType
        fields = [
            "id",
            "name",
            "description",
            "logo_props",
            "is_epic",
            "is_default",
            "is_active",
            "level",
            "workspace_id",
            "project_ids",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["workspace_id", "is_default", "level", "created_at", "updated_at"]

    def get_project_ids(self, obj):
        # Prefetched as `active_project_links` by the views; fall back to a query otherwise.
        links = getattr(obj, "active_project_links", None)
        if links is None:
            links = obj.project_issue_types.all()
        return [str(link.project_id) for link in links]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name is required")
        return value

    def validate_logo_props(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("logo_props must be an object")
        return value
