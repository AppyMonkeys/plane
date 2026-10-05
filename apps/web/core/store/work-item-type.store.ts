/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { set, sortBy } from "lodash-es";
import { action, makeObservable, observable, runInAction } from "mobx";
import { computedFn } from "mobx-utils";
// plane imports
import type { TWorkItemType } from "@plane/types";
// services
import { IssueTypeService } from "@/services/issue";
// store
import type { CoreRootStore } from "./root.store";

export interface IWorkItemTypeStore {
  // observables
  typeMap: Record<string, TWorkItemType>;
  fetchedMap: Record<string, boolean>;
  // computed functions
  isWorkItemTypeEnabledForProject: (projectId: string | undefined | null) => boolean;
  getWorkItemTypeById: (typeId: string | undefined | null) => TWorkItemType | undefined;
  getProjectWorkItemTypes: (projectId: string | undefined | null) => TWorkItemType[];
  getProjectDefaultWorkItemType: (projectId: string | undefined | null) => TWorkItemType | undefined;
  // actions
  fetchWorkspaceWorkItemTypes: (workspaceSlug: string) => Promise<TWorkItemType[]>;
  fetchProjectWorkItemTypes: (workspaceSlug: string, projectId: string) => Promise<TWorkItemType[]>;
  createWorkItemType: (
    workspaceSlug: string,
    projectId: string,
    data: Partial<TWorkItemType>
  ) => Promise<TWorkItemType>;
  updateWorkItemType: (
    workspaceSlug: string,
    projectId: string,
    typeId: string,
    data: Partial<TWorkItemType>
  ) => Promise<TWorkItemType>;
  markWorkItemTypeAsDefault: (workspaceSlug: string, projectId: string, typeId: string) => Promise<void>;
  deleteWorkItemType: (workspaceSlug: string, projectId: string, typeId: string) => Promise<void>;
}

export class WorkItemTypeStore implements IWorkItemTypeStore {
  typeMap: Record<string, TWorkItemType> = {};
  fetchedMap: Record<string, boolean> = {};
  // root store
  rootStore: CoreRootStore;
  // services
  issueTypeService: IssueTypeService;

  constructor(_rootStore: CoreRootStore) {
    makeObservable(this, {
      typeMap: observable,
      fetchedMap: observable,
      fetchWorkspaceWorkItemTypes: action,
      fetchProjectWorkItemTypes: action,
      createWorkItemType: action,
      updateWorkItemType: action,
      markWorkItemTypeAsDefault: action,
      deleteWorkItemType: action,
    });
    this.rootStore = _rootStore;
    this.issueTypeService = new IssueTypeService();
  }

  /**
   * Whether the project has work item types switched on
   */
  isWorkItemTypeEnabledForProject = computedFn(
    (projectId: string | undefined | null) =>
      !!projectId && !!this.rootStore.projectRoot.project.getPartialProjectById(projectId)?.is_issue_type_enabled
  );

  getWorkItemTypeById = computedFn((typeId: string | undefined | null) => (typeId ? this.typeMap[typeId] : undefined));

  /**
   * Work item types of a project, in display order -- including the disabled ones (which stay on the work
   * items that already have them but can no longer be picked).
   * Note: computedFn needs the same number of arguments on every call, so this takes the project id only.
   */
  getProjectWorkItemTypes = computedFn((projectId: string | undefined | null) => {
    if (!projectId) return [];
    return sortBy(
      Object.values(this.typeMap).filter((type) => type.project_ids?.includes(projectId)),
      ["level", "created_at"]
    );
  });

  getProjectDefaultWorkItemType = computedFn((projectId: string | undefined | null) =>
    this.getProjectWorkItemTypes(projectId).find((type) => type.is_default && type.is_active)
  );

  fetchWorkspaceWorkItemTypes = async (workspaceSlug: string) => {
    const response = await this.issueTypeService.getWorkspaceIssueTypes(workspaceSlug);
    runInAction(() => {
      response.forEach((type) => set(this.typeMap, [type.id], type));
      set(this.fetchedMap, workspaceSlug, true);
    });
    return response;
  };

  fetchProjectWorkItemTypes = async (workspaceSlug: string, projectId: string) => {
    const response = await this.issueTypeService.getProjectIssueTypes(workspaceSlug, projectId);
    runInAction(() => {
      // drop the project's types that no longer exist before writing the fresh list
      const freshIds = new Set(response.map((type) => type.id));
      Object.values(this.typeMap).forEach((type) => {
        if (type.project_ids?.includes(projectId) && !freshIds.has(type.id)) delete this.typeMap[type.id];
      });
      response.forEach((type) => set(this.typeMap, [type.id], type));
      set(this.fetchedMap, projectId, true);
    });
    return response;
  };

  createWorkItemType = async (workspaceSlug: string, projectId: string, data: Partial<TWorkItemType>) => {
    const response = await this.issueTypeService.createIssueType(workspaceSlug, projectId, data);
    runInAction(() => set(this.typeMap, [response.id], response));
    return response;
  };

  updateWorkItemType = async (
    workspaceSlug: string,
    projectId: string,
    typeId: string,
    data: Partial<TWorkItemType>
  ) => {
    const response = await this.issueTypeService.patchIssueType(workspaceSlug, projectId, typeId, data);
    runInAction(() => set(this.typeMap, [response.id], response));
    return response;
  };

  markWorkItemTypeAsDefault = async (workspaceSlug: string, projectId: string, typeId: string) => {
    await this.issueTypeService.markIssueTypeAsDefault(workspaceSlug, projectId, typeId);
    runInAction(() => {
      this.getProjectWorkItemTypes(projectId).forEach((type) => {
        set(this.typeMap, [type.id, "is_default"], type.id === typeId);
      });
    });
  };

  deleteWorkItemType = async (workspaceSlug: string, projectId: string, typeId: string) => {
    await this.issueTypeService.deleteIssueType(workspaceSlug, projectId, typeId);
    runInAction(() => {
      delete this.typeMap[typeId];
    });
  };
}
