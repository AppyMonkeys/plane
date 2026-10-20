/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { set, sortBy } from "lodash-es";
import { action, makeObservable, observable, runInAction } from "mobx";
import { computedFn } from "mobx-utils";
// plane imports
import type { TWorkItemTemplate } from "@plane/types";
// services
import { WorkItemTemplateService } from "@/services/issue";

export interface IWorkItemTemplateStore {
  // observables
  templateMap: Record<string, TWorkItemTemplate>;
  fetchedMap: Record<string, boolean>;
  // computed functions
  getTemplateById: (templateId: string | undefined | null) => TWorkItemTemplate | undefined;
  getProjectTemplates: (projectId: string | undefined | null) => TWorkItemTemplate[];
  // actions
  fetchProjectTemplates: (workspaceSlug: string, projectId: string) => Promise<TWorkItemTemplate[]>;
  createTemplate: (
    workspaceSlug: string,
    projectId: string,
    data: Partial<TWorkItemTemplate>
  ) => Promise<TWorkItemTemplate>;
  updateTemplate: (
    workspaceSlug: string,
    projectId: string,
    templateId: string,
    data: Partial<TWorkItemTemplate>
  ) => Promise<TWorkItemTemplate>;
  deleteTemplate: (workspaceSlug: string, projectId: string, templateId: string) => Promise<void>;
}

export class WorkItemTemplateStore implements IWorkItemTemplateStore {
  templateMap: Record<string, TWorkItemTemplate> = {};
  fetchedMap: Record<string, boolean> = {};
  // services
  templateService: WorkItemTemplateService;

  constructor() {
    makeObservable(this, {
      templateMap: observable,
      fetchedMap: observable,
      fetchProjectTemplates: action,
      createTemplate: action,
      updateTemplate: action,
      deleteTemplate: action,
    });
    this.templateService = new WorkItemTemplateService();
  }

  getTemplateById = computedFn((templateId: string | undefined | null) =>
    templateId ? this.templateMap[templateId] : undefined
  );

  /** Templates of a project, by name. Note: computedFn needs the same number of arguments on every call. */
  getProjectTemplates = computedFn((projectId: string | undefined | null) => {
    if (!projectId) return [];
    return sortBy(
      Object.values(this.templateMap).filter((template) => template.project_id === projectId),
      (template) => template.name.toLowerCase()
    );
  });

  fetchProjectTemplates = async (workspaceSlug: string, projectId: string) => {
    const response = await this.templateService.list(workspaceSlug, projectId);
    runInAction(() => {
      // drop the project's templates that were deleted elsewhere before writing the fresh list
      Object.values(this.templateMap).forEach((template) => {
        if (template.project_id === projectId) delete this.templateMap[template.id];
      });
      response.forEach((template) => set(this.templateMap, [template.id], template));
      set(this.fetchedMap, projectId, true);
    });
    return response;
  };

  createTemplate = async (workspaceSlug: string, projectId: string, data: Partial<TWorkItemTemplate>) => {
    const response = await this.templateService.create(workspaceSlug, projectId, data);
    runInAction(() => set(this.templateMap, [response.id], response));
    return response;
  };

  updateTemplate = async (
    workspaceSlug: string,
    projectId: string,
    templateId: string,
    data: Partial<TWorkItemTemplate>
  ) => {
    const response = await this.templateService.update(workspaceSlug, projectId, templateId, data);
    runInAction(() => set(this.templateMap, [response.id], response));
    return response;
  };

  deleteTemplate = async (workspaceSlug: string, projectId: string, templateId: string) => {
    await this.templateService.remove(workspaceSlug, projectId, templateId);
    runInAction(() => {
      delete this.templateMap[templateId];
    });
  };
}
