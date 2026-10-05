# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response

# Module imports
from .base import BaseAPIView
from plane.api.serializers import IssueTypeSerializer
from plane.app.permissions import ProjectEntityPermission
from plane.db.models import IssueType, Project
from plane.utils.issue_types import create_project_issue_type, default_logo_for, project_issue_types


class IssueTypeListCreateAPIEndpoint(BaseAPIView):
    """Work item type List and Create Endpoint"""

    serializer_class = IssueTypeSerializer
    model = IssueType
    permission_classes = [ProjectEntityPermission]

    def get_queryset(self):
        return project_issue_types(self.kwargs.get("project_id")).filter(workspace__slug=self.kwargs.get("slug"))

    @extend_schema(
        operation_id="list_work_item_types",
        summary="List work item types",
        description="List the work item types (Task, Bug, Story, ...) of a project.",
        tags=["Work Item Types"],
        responses={200: IssueTypeSerializer(many=True)},
    )
    def get(self, request, slug, project_id):
        """List work item types

        Returns every work item type of the project, in display order.
        """
        return Response(IssueTypeSerializer(self.get_queryset(), many=True).data, status=status.HTTP_200_OK)

    @extend_schema(
        operation_id="create_work_item_type",
        summary="Create work item type",
        description="Create a work item type for a project.",
        tags=["Work Item Types"],
        request=IssueTypeSerializer,
        responses={201: IssueTypeSerializer},
    )
    def post(self, request, slug, project_id):
        """Create work item type

        Creates a work item type for the project. Names are unique per project (case-insensitive).
        """
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        serializer = IssueTypeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        name = serializer.validated_data["name"].strip()
        existing = self.get_queryset().filter(name__iexact=name).first()
        if existing:
            return Response(
                {"error": "Work item type with the same name already exists", "id": str(existing.id)},
                status=status.HTTP_409_CONFLICT,
            )

        fields = {**serializer.validated_data, "name": name}
        if not fields.get("logo_props"):
            fields["logo_props"] = default_logo_for(name)
        fields["is_default"] = not self.get_queryset().exists()

        issue_type = create_project_issue_type(project, **fields)
        return Response(IssueTypeSerializer(issue_type).data, status=status.HTTP_201_CREATED)
