# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path


from plane.app.views import WorkItemTemplateViewSet


urlpatterns = [
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/work-item-templates/",
        WorkItemTemplateViewSet.as_view({"get": "list", "post": "create"}),
        name="project-work-item-templates",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/work-item-templates/<uuid:pk>/",
        WorkItemTemplateViewSet.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="project-work-item-template",
    ),
]
