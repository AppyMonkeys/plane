# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path, re_path

from plane.api.views.jira_compat import (
    JiraBrowseRedirectEndpoint,
    JiraIssueCommentEndpoint,
    JiraIssueEndpoint,
    JiraIssueTransitionsEndpoint,
    JiraMyselfEndpoint,
    JiraSearchEndpoint,
)

# Mounted at /api/jira/ (see plane/urls.py). <version> is Jira's REST version (2, 3 or latest);
# the answers are the same for all of them.
VERSION = r"rest/api/(?P<version>2|3|latest)"

urlpatterns = [
    re_path(rf"^{VERSION}/myself/?$", JiraMyselfEndpoint.as_view(), name="jira-myself"),
    re_path(rf"^{VERSION}/search(?:/jql)?/?$", JiraSearchEndpoint.as_view(), name="jira-search"),
    re_path(rf"^{VERSION}/issue/(?P<key>[^/]+)/?$", JiraIssueEndpoint.as_view(), name="jira-issue"),
    re_path(
        rf"^{VERSION}/issue/(?P<key>[^/]+)/transitions/?$",
        JiraIssueTransitionsEndpoint.as_view(),
        name="jira-issue-transitions",
    ),
    re_path(
        rf"^{VERSION}/issue/(?P<key>[^/]+)/comment/?$",
        JiraIssueCommentEndpoint.as_view(),
        name="jira-issue-comment",
    ),
    path("browse/<str:key>", JiraBrowseRedirectEndpoint.as_view(), name="jira-browse"),
]
