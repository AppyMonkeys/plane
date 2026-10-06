/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { ArrowNarrowLeftOutline, InboxOutline } from "@makeplane/propel/icons";
import { Tooltip } from "@makeplane/propel/components/tooltip";
import { IconButton } from "@plane/propel/icon-button";
import { Breadcrumbs, Header } from "@plane/ui";
// components
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
// helpers
import { getLastVisitedProjectId } from "@/helpers/last-visited-project.helper";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useAppRouter } from "@/hooks/use-app-router";
// local imports
import { NotificationSidebarHeaderOptions } from "./options";

type TNotificationSidebarHeader = {
  workspaceSlug: string;
};

export const NotificationSidebarHeader = observer(function NotificationSidebarHeader(
  props: TNotificationSidebarHeader
) {
  const { workspaceSlug } = props;
  const { t } = useTranslation();
  // router
  const router = useAppRouter();
  // store hooks
  const { getPartialProjectById } = useProject();

  if (!workspaceSlug) return <></>;

  // the project the user last had open; falls back to the workspace home when there is none
  // (fresh login straight into the Inbox, or the project is gone / no longer accessible)
  const lastVisitedProject = getPartialProjectById(getLastVisitedProjectId(workspaceSlug));
  const backHref = lastVisitedProject
    ? `/${workspaceSlug}/projects/${lastVisitedProject.id}/issues/`
    : `/${workspaceSlug}/`;
  const backLabel = lastVisitedProject
    ? t("notification.back_to_project", { project: lastVisitedProject.name })
    : t("notification.back_to_home");

  return (
    <Header className="my-auto bg-surface-1">
      <Header.LeftItem>
        <Tooltip label={backLabel} side="bottom">
          <IconButton
            size="base"
            variant="ghost"
            icon={ArrowNarrowLeftOutline}
            aria-label={backLabel}
            onClick={() => router.push(backHref)}
          />
        </Tooltip>
        <Breadcrumbs>
          <Breadcrumbs.Item
            component={
              <BreadcrumbLink
                label={t("notification.label")}
                icon={<InboxOutline className="h-4 w-4 text-primary" />}
                disableTooltip
              />
            }
          />
        </Breadcrumbs>
      </Header.LeftItem>
      <Header.RightItem>
        <NotificationSidebarHeaderOptions workspaceSlug={workspaceSlug} />
      </Header.RightItem>
    </Header>
  );
});
