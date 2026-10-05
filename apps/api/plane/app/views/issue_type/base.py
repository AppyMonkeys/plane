# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db.models import Prefetch

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from .. import BaseAPIView, BaseViewSet
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import IssueTypeSerializer
from plane.db.models import Issue, IssueType, Project, ProjectIssueType
from plane.utils.issue_types import (
    create_project_issue_type,
    default_logo_for,
    mark_default_issue_type,
    project_issue_types,
)


def with_project_links(queryset):
    return queryset.prefetch_related(
        Prefetch(
            "project_issue_types",
            queryset=ProjectIssueType.objects.filter(deleted_at__isnull=True),
            to_attr="active_project_links",
        )
    )


class WorkspaceIssueTypesEndpoint(BaseAPIView):
    """Every work item type in the projects the user can see -- used to render type icons anywhere."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        issue_types = with_project_links(
            IssueType.objects.filter(
                workspace__slug=slug,
                project_issue_types__deleted_at__isnull=True,
                project_issue_types__project__project_projectmember__member=request.user,
                project_issue_types__project__project_projectmember__is_active=True,
                project_issue_types__project__archived_at__isnull=True,
            )
            .distinct()
            .order_by("level", "created_at")
        )
        return Response(IssueTypeSerializer(issue_types, many=True).data, status=status.HTTP_200_OK)


class IssueTypeViewSet(BaseViewSet):
    serializer_class = IssueTypeSerializer
    model = IssueType

    def get_project_type(self, slug, project_id, pk):
        return with_project_links(project_issue_types(project_id).filter(workspace__slug=slug)).get(pk=pk)

    def name_taken(self, project_id, name, exclude_id=None):
        queryset = project_issue_types(project_id).filter(name__iexact=name)
        if exclude_id:
            queryset = queryset.exclude(pk=exclude_id)
        return queryset.exists()

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def list(self, request, slug, project_id):
        issue_types = with_project_links(project_issue_types(project_id).filter(workspace__slug=slug))
        return Response(IssueTypeSerializer(issue_types, many=True).data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def create(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        serializer = IssueTypeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        name = serializer.validated_data["name"]
        if self.name_taken(project_id, name):
            return Response(
                {"name": "A work item type with this name already exists"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fields = dict(serializer.validated_data)
        if not fields.get("logo_props"):
            fields["logo_props"] = default_logo_for(name)
        # The first type of a project becomes its default.
        fields["is_default"] = not project_issue_types(project_id).exists()

        issue_type = create_project_issue_type(project, **fields)
        return Response(
            IssueTypeSerializer(self.get_project_type(slug, project_id, issue_type.id)).data,
            status=status.HTTP_201_CREATED,
        )

    @allow_permission([ROLE.ADMIN])
    def partial_update(self, request, slug, project_id, pk):
        issue_type = self.get_project_type(slug, project_id, pk)
        serializer = IssueTypeSerializer(issue_type, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        name = serializer.validated_data.get("name")
        if name and self.name_taken(project_id, name, exclude_id=pk):
            return Response(
                {"name": "A work item type with this name already exists"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if issue_type.is_default and serializer.validated_data.get("is_active") is False:
            return Response(
                {"error": "The default work item type cannot be disabled"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer.save()
        return Response(
            IssueTypeSerializer(self.get_project_type(slug, project_id, pk)).data,
            status=status.HTTP_200_OK,
        )

    @allow_permission([ROLE.ADMIN])
    def mark_as_default(self, request, slug, project_id, pk):
        issue_type = self.get_project_type(slug, project_id, pk)
        if not issue_type.is_active:
            return Response(
                {"error": "Enable this work item type before making it the default"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        mark_default_issue_type(project_id, issue_type.id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @allow_permission([ROLE.ADMIN])
    def destroy(self, request, slug, project_id, pk):
        issue_type = self.get_project_type(slug, project_id, pk)

        if issue_type.is_default:
            return Response(
                {"error": "The default work item type cannot be deleted"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if Issue.objects.filter(type_id=pk).exists():
            return Response(
                {"error": "This work item type is in use. Move its work items to another type or disable it instead."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ProjectIssueType.objects.filter(issue_type_id=pk).delete()
        issue_type.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
