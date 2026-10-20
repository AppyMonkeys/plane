/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React, { useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { DEFAULT_WORK_ITEM_FORM_VALUES } from "@plane/constants";
import type { ISearchIssueResponse, TIssue } from "@plane/types";
// components
import { IssueModalContext } from "@/components/issues/issue-modal/context";
import type { THandleTemplateChangeProps } from "@/components/issues/issue-modal/context";
import { getApplicableTemplateData } from "@/components/work-item-templates/helpers";
// hooks
import { useLabel } from "@/hooks/store/use-label";
import { useMember } from "@/hooks/store/use-member";
import { useModule } from "@/hooks/store/use-module";
import { useProjectState } from "@/hooks/store/use-project-state";
import { useWorkItemTemplate } from "@/hooks/store/use-work-item-template";
import { useWorkItemType } from "@/hooks/store/use-work-item-type";
import { useUser } from "@/hooks/store/user/user-user";

export type TIssueModalProviderProps = {
  templateId?: string;
  dataForPreload?: Partial<TIssue>;
  allowedProjectIds?: string[];
  children: React.ReactNode;
};

export const IssueModalProvider = observer(function IssueModalProvider(props: TIssueModalProviderProps) {
  const { children, allowedProjectIds } = props;
  // states
  const [selectedParentIssue, setSelectedParentIssue] = useState<ISearchIssueResponse | null>(null);
  const [pendingAttachments, setPendingAttachments] = useState<File[]>([]);
  const [workItemTemplateId, setWorkItemTemplateId] = useState<string | null>(null);
  const [isApplyingTemplate, setIsApplyingTemplate] = useState(false);
  // store hooks
  const { projectsWithCreatePermissions } = useUser();
  const { isWorkItemTypeEnabledForProject, getProjectDefaultWorkItemType, getProjectWorkItemTypes } = useWorkItemType();
  const { getTemplateById } = useWorkItemTemplate();
  const { getProjectStateIds } = useProjectState();
  const { getProjectLabels } = useLabel();
  const {
    project: { getProjectMemberIds },
  } = useMember();
  const { getProjectModuleIds } = useModule();
  // derived values
  const projectIdsWithCreatePermissions = Object.keys(projectsWithCreatePermissions ?? {});

  const getIssueTypeIdOnProjectChange = (projectId: string) =>
    isWorkItemTypeEnabledForProject(projectId) ? (getProjectDefaultWorkItemType(projectId)?.id ?? null) : null;

  // fills the create form with the picked template (see WorkItemTemplateSelect)
  const handleTemplateChange = async ({ reset, editorRef }: THandleTemplateChangeProps) => {
    const template = getTemplateById(workItemTemplateId);
    if (!template) return;
    const projectId = template.project_id;
    const data = getApplicableTemplateData(template.template_data, {
      stateIds: getProjectStateIds(projectId) ?? [],
      typeIds: getProjectWorkItemTypes(projectId)
        .filter((type) => type.is_active)
        .map((type) => type.id),
      labelIds: (getProjectLabels(projectId) ?? []).map((label) => label.id),
      memberIds: getProjectMemberIds(projectId, true) ?? [],
      moduleIds: getProjectModuleIds(projectId) ?? [],
    });
    const descriptionHtml = data.description_html ?? "<p></p>";
    reset({
      ...DEFAULT_WORK_ITEM_FORM_VALUES,
      ...data,
      project_id: projectId,
      type_id: data.type_id ?? getIssueTypeIdOnProjectChange(projectId),
      description_html: descriptionHtml,
    });
    editorRef.current?.setEditorValue(descriptionHtml);
  };

  return (
    <IssueModalContext.Provider
      // oxlint-disable-next-line react/jsx-no-constructed-context-values
      value={{
        allowedProjectIds: allowedProjectIds ?? projectIdsWithCreatePermissions,
        workItemTemplateId,
        setWorkItemTemplateId,
        isApplyingTemplate,
        setIsApplyingTemplate,
        selectedParentIssue,
        setSelectedParentIssue,
        pendingAttachments,
        setPendingAttachments,
        issuePropertyValues: {},
        setIssuePropertyValues: () => {},
        issuePropertyValueErrors: {},
        setIssuePropertyValueErrors: () => {},
        getIssueTypeIdOnProjectChange,
        getActiveAdditionalPropertiesLength: () => 0,
        handlePropertyValuesValidation: () => true,
        handleCreateUpdatePropertyValues: () => Promise.resolve(),
        handleProjectEntitiesFetch: () => Promise.resolve(),
        handleTemplateChange,
        handleConvert: () => Promise.resolve(),
        handleCreateSubWorkItem: () => Promise.resolve(),
      }}
    >
      {children}
    </IssueModalContext.Provider>
  );
});
