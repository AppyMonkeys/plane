/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TWorkItemTemplate } from "@plane/types";
// services
import { APIService } from "@/services/api.service";

export class WorkItemTemplateService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private url(workspaceSlug: string, projectId: string, templateId?: string) {
    const base = `/api/workspaces/${workspaceSlug}/projects/${projectId}/work-item-templates/`;
    return templateId ? `${base}${templateId}/` : base;
  }

  async list(workspaceSlug: string, projectId: string): Promise<TWorkItemTemplate[]> {
    return this.get(this.url(workspaceSlug, projectId))
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async create(workspaceSlug: string, projectId: string, data: Partial<TWorkItemTemplate>): Promise<TWorkItemTemplate> {
    return this.post(this.url(workspaceSlug, projectId), data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async update(
    workspaceSlug: string,
    projectId: string,
    templateId: string,
    data: Partial<TWorkItemTemplate>
  ): Promise<TWorkItemTemplate> {
    return this.patch(this.url(workspaceSlug, projectId, templateId), data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async remove(workspaceSlug: string, projectId: string, templateId: string): Promise<void> {
    return this.delete(this.url(workspaceSlug, projectId, templateId))
      .then(() => undefined)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
