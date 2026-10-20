/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TWorkItemTemplate } from "@plane/types";
import { AlertModalCore, CustomMenu, Loader } from "@plane/ui";
import { stripAndTruncateHTML } from "@plane/utils";
// components
import { SettingsHeading } from "@/components/settings/heading";
// hooks
import { useWorkItemTemplate } from "@/hooks/store/use-work-item-template";
import { useUser, useUserPermissions } from "@/hooks/store/user";
// local imports
import { SaveWorkItemTemplateModal } from "../save-modal";

type TWorkItemTemplatesSettingsRootProps = {
  workspaceSlug: string;
  projectId: string;
};

export const WorkItemTemplatesSettingsRoot = observer(function WorkItemTemplatesSettingsRoot(
  props: TWorkItemTemplatesSettingsRootProps
) {
  const { workspaceSlug, projectId } = props;
  // plane hooks
  const { t } = useTranslation();
  // states
  const [renaming, setRenaming] = useState<TWorkItemTemplate | null>(null);
  const [deleting, setDeleting] = useState<TWorkItemTemplate | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  // store hooks
  const { data: currentUser } = useUser();
  const { allowPermissions } = useUserPermissions();
  const { getProjectTemplates, fetchProjectTemplates, deleteTemplate } = useWorkItemTemplate();
  // derived values
  const templates = getProjectTemplates(projectId);
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT);
  const { isLoading } = useSWR(`PROJECT_WORK_ITEM_TEMPLATES_${workspaceSlug}_${projectId}`, () =>
    fetchProjectTemplates(workspaceSlug, projectId)
  );

  const handleDelete = async () => {
    if (!deleting) return;
    setIsDeleting(true);
    try {
      await deleteTemplate(workspaceSlug, projectId, deleting.id);
      setToast({ type: TOAST_TYPE.SUCCESS, title: t("work_item_templates.settings.deleted") });
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("work_item_templates.settings.delete_error") });
    } finally {
      setIsDeleting(false);
      setDeleting(null);
    }
  };

  return (
    <div className="w-full">
      <SettingsHeading
        title={t("work_item_templates.settings.title")}
        description={t("work_item_templates.settings.description")}
      />
      <SaveWorkItemTemplateModal
        isOpen={!!renaming}
        onClose={() => setRenaming(null)}
        workspaceSlug={workspaceSlug}
        projectId={projectId}
        template={renaming ?? undefined}
      />
      <AlertModalCore
        isOpen={!!deleting}
        handleClose={() => setDeleting(null)}
        handleSubmit={() => void handleDelete()}
        isSubmitting={isDeleting}
        title={t("work_item_templates.settings.delete_title")}
        content={t("work_item_templates.settings.delete_content", { name: deleting?.name ?? "" })}
      />
      <div className="mt-6 flex flex-col gap-2">
        {isLoading && templates.length === 0 ? (
          <Loader className="space-y-2">
            <Loader.Item height="48px" />
            <Loader.Item height="48px" />
          </Loader>
        ) : templates.length === 0 ? (
          <p className="rounded-sm border border-subtle px-3.5 py-6 text-center text-body-xs-regular text-tertiary">
            {t("work_item_templates.settings.empty")}
          </p>
        ) : (
          templates.map((template) => {
            const summary = stripAndTruncateHTML(template.template_data.description_html ?? "", 120);
            const canDelete = isAdmin || template.created_by === currentUser?.id;
            return (
              <div
                key={template.id}
                className="flex items-center gap-3 rounded-sm border border-subtle bg-surface-1 px-3.5 py-2.5"
              >
                <div className="flex min-w-0 flex-grow flex-col">
                  <span className="truncate text-body-xs-medium text-primary">{template.name}</span>
                  {(template.template_data.name || summary) && (
                    <span className="truncate text-caption-sm-regular text-tertiary">
                      {[template.template_data.name, summary].filter(Boolean).join(" — ")}
                    </span>
                  )}
                </div>
                <CustomMenu ellipsis placement="bottom-end" closeOnSelect ariaLabel={template.name}>
                  <CustomMenu.MenuItem onClick={() => setRenaming(template)}>
                    {t("work_item_templates.settings.rename")}
                  </CustomMenu.MenuItem>
                  {canDelete && (
                    <CustomMenu.MenuItem onClick={() => setDeleting(template)}>
                      {t("work_item_templates.settings.delete")}
                    </CustomMenu.MenuItem>
                  )}
                </CustomMenu>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
});
