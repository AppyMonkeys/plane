/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { Tooltip } from "@makeplane/propel/components/tooltip";
import type { TIssueIdentifierProps } from "@plane/types";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useProject } from "@/hooks/store/use-project";
import { useWorkItemType } from "@/hooks/store/use-work-item-type";
import { IdentifierText } from "@/components/issues/issue-detail/identifier-text";
import { WorkItemTypeIcon } from "@/components/work-item-types/icon";

const TYPE_ICON_SIZE: Record<NonNullable<TIssueIdentifierProps["size"]>, number> = {
  xs: 14,
  sm: 14,
  md: 16,
  lg: 18,
};

export const IssueIdentifier = observer(function IssueIdentifier(props: TIssueIdentifierProps) {
  const { projectId, variant, size, displayProperties, enableClickToCopyIdentifier = false } = props;
  // store hooks
  const { getProjectIdentifierById } = useProject();
  const {
    issue: { getIssueById },
  } = useIssueDetail();
  // Determine if the component is using store data or not
  const isUsingStoreData = "issueId" in props;
  // derived values
  const issue = isUsingStoreData ? getIssueById(props.issueId) : null;
  const projectIdentifier = isUsingStoreData ? getProjectIdentifierById(projectId) : props.projectIdentifier;
  const issueSequenceId = isUsingStoreData ? issue?.sequence_id : props.issueSequenceId;
  const shouldRenderIssueID = displayProperties ? displayProperties.key : true;
  // work item type
  const { isWorkItemTypeEnabledForProject, getWorkItemTypeById } = useWorkItemType();
  const workItemTypeId = isUsingStoreData ? issue?.type_id : props.issueTypeId;
  const workItemType =
    (displayProperties ? displayProperties.issue_type !== false : true) && isWorkItemTypeEnabledForProject(projectId)
      ? getWorkItemTypeById(workItemTypeId)
      : undefined;

  if (!shouldRenderIssueID && !workItemType) return null;

  return (
    <div className="flex shrink-0 items-center space-x-2">
      {workItemType && (
        <Tooltip label={workItemType.name} side="top">
          <span className="flex shrink-0">
            <WorkItemTypeIcon logoProps={workItemType.logo_props} size={TYPE_ICON_SIZE[size ?? "sm"]} />
          </span>
        </Tooltip>
      )}
      {shouldRenderIssueID && (
        <IdentifierText
          identifier={`${projectIdentifier}-${issueSequenceId}`}
          enableClickToCopyIdentifier={enableClickToCopyIdentifier}
          variant={variant}
          size={size}
        />
      )}
    </div>
  );
});
