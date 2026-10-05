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
import { Button } from "@plane/propel/button";
import { Loader } from "@plane/ui";
// components
import { SettingsHeading } from "@/components/settings/heading";
import { ProjectSettingsFeatureControlItem } from "@/components/settings/project/content/feature-control-item";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useWorkItemType } from "@/hooks/store/use-work-item-type";
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import { WorkItemTypeForm } from "./form";
import { WorkItemTypeSettingsItem } from "./item";

type TWorkItemTypesSettingsRootProps = {
  workspaceSlug: string;
  projectId: string;
};

export const WorkItemTypesSettingsRoot = observer(function WorkItemTypesSettingsRoot(
  props: TWorkItemTypesSettingsRootProps
) {
  const { workspaceSlug, projectId } = props;
  // plane hooks
  const { t } = useTranslation();
  // states
  const [isCreating, setIsCreating] = useState(false);
  // store hooks
  const { getProjectById } = useProject();
  const { allowPermissions } = useUserPermissions();
  const { getProjectWorkItemTypes, fetchProjectWorkItemTypes, createWorkItemType } = useWorkItemType();
  // derived values
  const isEnabled = !!getProjectById(projectId)?.is_issue_type_enabled;
  const isEditable = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT);
  const workItemTypes = getProjectWorkItemTypes(projectId);
  // (re)fetch whenever the feature gets switched on -- that is when the default types are created
  const { isLoading } = useSWR(
    isEnabled ? `PROJECT_WORK_ITEM_TYPES_${workspaceSlug}_${projectId}` : null,
    isEnabled ? () => fetchProjectWorkItemTypes(workspaceSlug, projectId) : null,
    { revalidateIfStale: false, revalidateOnFocus: false }
  );

  return (
    <div className="w-full">
      <SettingsHeading
        title={t("work_item_types.label")}
        description={t("work_item_types.settings.project_description")}
        control={
          isEnabled &&
          isEditable && (
            <Button variant="primary" size="lg" onClick={() => setIsCreating(true)}>
              {t("work_item_types.settings.add_button")}
            </Button>
          )
        }
      />
      <div className="mt-7">
        <ProjectSettingsFeatureControlItem
          title={t("work_item_types.settings.toggle_title")}
          description={t("work_item_types.settings.toggle_description")}
          featureProperty="is_issue_type_enabled"
          projectId={projectId}
          value={isEnabled}
          workspaceSlug={workspaceSlug}
          disabled={!isEditable}
        />
      </div>
      {isEnabled && (
        <div className="mt-6 flex flex-col gap-2">
          {isCreating && (
            <WorkItemTypeForm
              onSubmit={async (data) => {
                await createWorkItemType(workspaceSlug, projectId, data);
              }}
              onClose={() => setIsCreating(false)}
            />
          )}
          {isLoading && workItemTypes.length === 0 ? (
            <Loader className="space-y-2">
              <Loader.Item height="48px" />
              <Loader.Item height="48px" />
              <Loader.Item height="48px" />
            </Loader>
          ) : (
            workItemTypes.map((workItemType) => (
              <WorkItemTypeSettingsItem
                key={workItemType.id}
                workspaceSlug={workspaceSlug}
                projectId={projectId}
                workItemType={workItemType}
                isEditable={isEditable}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
});
