# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from .. import BaseViewSet
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import WorkItemTemplateSerializer
from plane.db.models import Project, WorkItemTemplate


class WorkItemTemplateViewSet(BaseViewSet):
    """Work item templates of a project: everyone in it can use them, members and admins keep them up to date."""

    serializer_class = WorkItemTemplateSerializer
    model = WorkItemTemplate

    def get_templates(self, slug, project_id):
        return WorkItemTemplate.objects.filter(workspace__slug=slug, project_id=project_id)

    def name_taken_response(self, slug, project_id, name, exclude_id=None):
        queryset = self.get_templates(slug, project_id).filter(name__iexact=name)
        if exclude_id:
            queryset = queryset.exclude(pk=exclude_id)
        if not queryset.exists():
            return None
        return Response(
            {"name": "A template with this name already exists"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def list(self, request, slug, project_id):
        templates = self.get_templates(slug, project_id)
        return Response(WorkItemTemplateSerializer(templates, many=True).data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def create(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        serializer = WorkItemTemplateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        taken = self.name_taken_response(slug, project_id, serializer.validated_data["name"])
        if taken:
            return taken
        serializer.save(project=project)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def partial_update(self, request, slug, project_id, pk):
        template = self.get_templates(slug, project_id).get(pk=pk)
        serializer = WorkItemTemplateSerializer(template, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        name = serializer.validated_data.get("name")
        taken = name and self.name_taken_response(slug, project_id, name, exclude_id=pk)
        if taken:
            return taken
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    # project admins, and whoever made the template
    @allow_permission([ROLE.ADMIN], creator=True, model=WorkItemTemplate)
    def destroy(self, request, slug, project_id, pk):
        self.get_templates(slug, project_id).get(pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
