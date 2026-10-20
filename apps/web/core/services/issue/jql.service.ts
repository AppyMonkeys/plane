/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TIssueOrderByOptions, TWorkItemFilterExpression } from "@plane/types";
// services
import { APIService } from "@/services/api.service";

export type TJQLParseResponse = {
  filters: TWorkItemFilterExpression;
  order_by: TIssueOrderByOptions | null;
};

/** Translates the filter bar's JQL to filters and back (the server knows the names behind the ids). */
export class JQLService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private url(workspaceSlug: string, projectId: string) {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}/jql/`;
  }

  async parse(workspaceSlug: string, projectId: string, jql: string): Promise<TJQLParseResponse> {
    return this.post(this.url(workspaceSlug, projectId), { jql })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async format(
    workspaceSlug: string,
    projectId: string,
    filters: TWorkItemFilterExpression,
    orderBy: string | undefined
  ): Promise<string> {
    return this.post(this.url(workspaceSlug, projectId), { filters, order_by: orderBy })
      .then((response) => response?.data?.jql)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
