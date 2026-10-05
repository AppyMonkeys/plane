/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
// components
import { IdentifierText } from "@/components/issues/issue-detail/identifier-text";
import { IssueIdentifier } from "@/components/issues/issue-detail/issue-identifier";
import { WorkItemTypeDropdown } from "@/components/work-item-types/dropdown";
// store hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useProject } from "@/hooks/store/use-project";
import { useWorkItemType } from "@/hooks/store/use-work-item-type";

export type TIssueTypeSwitcherProps = {
  issueId: string;
  disabled: boolean;
};

export const IssueTypeSwitcher = observer(function IssueTypeSwitcher(props: TIssueTypeSwitcherProps) {
  const { issueId, disabled } = props;
  // router
  const { workspaceSlug } = useParams();
  // plane hooks
  const { t } = useTranslation();
  // store hooks
  const {
    issue: { getIssueById },
    updateIssue,
  } = useIssueDetail();
  const { getProjectIdentifierById } = useProject();
  const { isWorkItemTypeEnabledForProject, getProjectWorkItemTypes } = useWorkItemType();
  // derived values
  const issue = getIssueById(issueId);

  if (!issue || !issue.project_id) return <></>;

  const projectId = issue.project_id;
  const canSwitchType = isWorkItemTypeEnabledForProject(projectId) && getProjectWorkItemTypes(projectId).length > 0;

  if (!canSwitchType)
    return <IssueIdentifier issueId={issueId} projectId={projectId} size="md" enableClickToCopyIdentifier />;

  const handleTypeChange = async (typeId: string) => {
    if (!workspaceSlug) return;
    try {
      await updateIssue(workspaceSlug.toString(), projectId, issueId, { type_id: typeId });
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t("toast.error"),
        message: t("work_item_types.toast.change_type_error"),
      });
    }
  };

  return (
    <div className="flex shrink-0 items-center gap-1.5">
      <WorkItemTypeDropdown
        projectId={projectId}
        value={issue.type_id}
        onChange={(typeId) => void handleTypeChange(typeId)}
        disabled={disabled}
        variant={issue.type_id ? "icon" : "button"}
      />
      <IdentifierText
        identifier={`${getProjectIdentifierById(projectId)}-${issue.sequence_id}`}
        enableClickToCopyIdentifier
        size="md"
      />
    </div>
  );
});
