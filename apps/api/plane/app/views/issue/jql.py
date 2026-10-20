# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from .. import BaseAPIView
from plane.app.permissions import ROLE, allow_permission
from plane.db.models import Project
from plane.utils.jql import JQLError
from plane.utils.jql_filters import filters_to_jql, jql_to_filters


class ProjectJQLEndpoint(BaseAPIView):
    """JQL mode of the work items filter bar: JQL -> filter expression, or back."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def post(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id, workspace__slug=slug)
        try:
            if "jql" in request.data:
                filters, order_by = jql_to_filters(request.data.get("jql") or "", project, request.user)
                return Response({"filters": filters, "order_by": order_by}, status=status.HTTP_200_OK)
            jql = filters_to_jql(request.data.get("filters") or {}, request.data.get("order_by"), project, request.user)
            return Response({"jql": jql}, status=status.HTTP_200_OK)
        except JQLError as error:
            return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)
