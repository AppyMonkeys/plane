/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { Tooltip } from "@makeplane/propel/components/tooltip";
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { IState, ISearchIssueResponse } from "@plane/types";
// components
import { ExistingIssuesListModal } from "@/components/core/modals/existing-issues-list-modal";
import { StateDropdown } from "@/components/dropdowns/state/dropdown";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useProjectState } from "@/hooks/store/use-project-state";

const CLOSED_STATE_GROUPS = new Set(["completed", "cancelled"]);

const isNamed = (state: IState | undefined, name: string) => state?.name.trim().toLowerCase() === name;

type TIssueStateSelect = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  disabled?: boolean;
  buttonClassName?: string;
  onChange: (stateId: string) => Promise<void> | void;
};

/**
 * The state field of an open work item, with two Jira-style extras: a Reopen button while the work
 * item is closed, and a prompt for the original work item when it's moved to "Duplicate".
 */
export const IssueStateSelect = observer(function IssueStateSelect(props: TIssueStateSelect) {
  const { workspaceSlug, projectId, issueId, disabled = false, buttonClassName, onChange } = props;
  // plane hooks
  const { t } = useTranslation();
  // store hooks
  const {
    issue: { getIssueById },
    createRelation,
  } = useIssueDetail();
  const { getStateById, getProjectStates, getProjectDefaultStateId } = useProjectState();
  // states
  const [isDuplicateModalOpen, setIsDuplicateModalOpen] = useState(false);
  // derived values
  const issue = getIssueById(issueId);
  const currentState = getStateById(issue?.state_id);
  const isClosed = !!currentState && CLOSED_STATE_GROUPS.has(currentState.group);
  // projects without a Reopened state go back to their default state
  const reopenStateId =
    getProjectStates(projectId)?.find((state) => isNamed(state, "reopened"))?.id ?? getProjectDefaultStateId(projectId);

  const handleChange = async (stateId: string) => {
    await onChange(stateId);
    if (isNamed(getStateById(stateId), "duplicate")) setIsDuplicateModalOpen(true);
  };

  const handleDuplicateOf = async (originals: ISearchIssueResponse[]) => {
    await createRelation(
      workspaceSlug,
      projectId,
      issueId,
      "duplicate",
      originals.map((original) => original.id)
    );
    setToast({
      type: TOAST_TYPE.SUCCESS,
      title: t("issue.duplicate_of.success_title"),
      message: t("issue.duplicate_of.success", {
        ids: originals.map((original) => `${original.project__identifier}-${original.sequence_id}`).join(", "),
      }),
    });
    setIsDuplicateModalOpen(false);
  };

  return (
    <div className="flex w-full items-center gap-1">
      <StateDropdown
        value={issue?.state_id}
        onChange={(stateId) => void handleChange(stateId)}
        projectId={projectId}
        disabled={disabled}
        buttonVariant="transparent-with-text"
        className="group w-full grow"
        buttonContainerClassName="w-full text-left h-7.5"
        buttonClassName={buttonClassName}
        dropdownArrow
        dropdownArrowClassName="h-3.5 w-3.5 hidden group-hover:inline"
      />
      {isClosed && !disabled && reopenStateId && reopenStateId !== issue?.state_id && (
        <Tooltip label={t("issue.reopen.tooltip")} side="bottom">
          <button
            type="button"
            className="flex-shrink-0 rounded-sm border-[0.5px] border-strong px-2 py-0.5 text-caption-sm-medium text-secondary hover:bg-layer-1"
            onClick={() => void onChange(reopenStateId)}
          >
            {t("issue.reopen.label")}
          </button>
        </Tooltip>
      )}
      <ExistingIssuesListModal
        workspaceSlug={workspaceSlug}
        projectId={projectId}
        isOpen={isDuplicateModalOpen}
        handleClose={() => setIsDuplicateModalOpen(false)}
        searchParams={{ issue_relation: true, issue_id: issueId }}
        handleOnSubmit={handleDuplicateOf}
        workspaceLevelToggle
      />
    </div>
  );
});
