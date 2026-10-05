/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TWorkItemType } from "@plane/types";
import { AlertModalCore, CustomMenu } from "@plane/ui";
// hooks
import { useWorkItemType } from "@/hooks/store/use-work-item-type";
// local imports
import { WorkItemTypeIcon } from "../icon";
import { WorkItemTypeForm } from "./form";

type TWorkItemTypeSettingsItemProps = {
  workspaceSlug: string;
  projectId: string;
  workItemType: TWorkItemType;
  isEditable: boolean;
};

export const WorkItemTypeSettingsItem = observer(function WorkItemTypeSettingsItem(
  props: TWorkItemTypeSettingsItemProps
) {
  const { workspaceSlug, projectId, workItemType, isEditable } = props;
  // plane hooks
  const { t } = useTranslation();
  // states
  const [isEditing, setIsEditing] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  // store hooks
  const { updateWorkItemType, markWorkItemTypeAsDefault, deleteWorkItemType } = useWorkItemType();

  const showError = (error: unknown) =>
    setToast({
      type: TOAST_TYPE.ERROR,
      title: t("toast.error"),
      message: (error as { error?: string } | undefined)?.error ?? t("work_item_types.settings.toast.error"),
    });

  const handleToggleActive = () =>
    updateWorkItemType(workspaceSlug, projectId, workItemType.id, { is_active: !workItemType.is_active }).catch(
      showError
    );

  const handleMarkDefault = () => markWorkItemTypeAsDefault(workspaceSlug, projectId, workItemType.id).catch(showError);

  const handleDelete = async () => {
    setIsDeleting(true);
    try {
      await deleteWorkItemType(workspaceSlug, projectId, workItemType.id);
      setIsDeleteModalOpen(false);
    } catch (error) {
      setIsDeleteModalOpen(false);
      showError(error);
    } finally {
      setIsDeleting(false);
    }
  };

  if (isEditing)
    return (
      <WorkItemTypeForm
        data={workItemType}
        onSubmit={async (data) => {
          await updateWorkItemType(workspaceSlug, projectId, workItemType.id, data);
        }}
        onClose={() => setIsEditing(false)}
      />
    );

  return (
    <>
      <AlertModalCore
        isOpen={isDeleteModalOpen}
        handleClose={() => setIsDeleteModalOpen(false)}
        handleSubmit={() => void handleDelete()}
        isSubmitting={isDeleting}
        title={t("work_item_types.settings.delete.title")}
        content={t("work_item_types.settings.delete.description", { name: workItemType.name })}
      />
      <div className="group flex items-center gap-3 rounded-sm border border-subtle bg-surface-1 px-3.5 py-2.5">
        <WorkItemTypeIcon
          logoProps={workItemType.logo_props}
          size={20}
          className={workItemType.is_active ? "" : "opacity-50"}
        />
        <div className="flex min-w-0 flex-grow flex-col">
          <div className="flex items-center gap-2">
            <span
              className={`truncate text-body-xs-medium ${workItemType.is_active ? "text-primary" : "text-tertiary"}`}
            >
              {workItemType.name}
            </span>
            {workItemType.is_default && (
              <span className="rounded-sm bg-accent-subtle px-1.5 py-0.5 text-caption-xs-medium text-accent-primary">
                {t("common.default")}
              </span>
            )}
            {!workItemType.is_active && (
              <span className="rounded-sm bg-layer-1 px-1.5 py-0.5 text-caption-xs-medium text-tertiary">
                {t("common.disabled")}
              </span>
            )}
          </div>
          {workItemType.description && (
            <span className="truncate text-caption-sm-regular text-tertiary">{workItemType.description}</span>
          )}
        </div>
        {isEditable && (
          <CustomMenu ellipsis placement="bottom-end" closeOnSelect ariaLabel={workItemType.name}>
            <CustomMenu.MenuItem onClick={() => setIsEditing(true)}>{t("common.edit")}</CustomMenu.MenuItem>
            {!workItemType.is_default && workItemType.is_active && (
              <CustomMenu.MenuItem onClick={() => void handleMarkDefault()}>
                {t("work_item_types.settings.set_as_default")}
              </CustomMenu.MenuItem>
            )}
            {!workItemType.is_default && (
              <CustomMenu.MenuItem onClick={() => void handleToggleActive()}>
                {workItemType.is_active ? t("work_item_types.settings.disable") : t("work_item_types.settings.enable")}
              </CustomMenu.MenuItem>
            )}
            {!workItemType.is_default && (
              <CustomMenu.MenuItem onClick={() => setIsDeleteModalOpen(true)}>{t("common.delete")}</CustomMenu.MenuItem>
            )}
          </CustomMenu>
        )}
      </div>
    </>
  );
});
