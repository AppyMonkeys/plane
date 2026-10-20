/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { isEqual } from "lodash-es";
import { observer } from "mobx-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { IWorkItemFilterInstance } from "@plane/shared-state";
import type { IProjectView } from "@plane/types";
import { EViewAccess } from "@plane/types";
import { FavoriteStar } from "@plane/ui";
import { cn } from "@plane/utils";
// hooks
import { useProjectView } from "@/hooks/store/use-project-view";
import { useUser } from "@/hooks/store/user";
// local imports
import { FilterBarDropdown } from "./dropdown";

type TFilterBarSavedFiltersProps = {
  filter: IWorkItemFilterInstance;
  workspaceSlug: string;
  projectId: string;
  /** The saved filter last opened here, if any. */
  appliedViewId: string | null;
  onApply: (view: IProjectView | null) => void;
};

/**
 * Jira's "Filters" menu and "Save filter" button. Saved filters are Plane views of the project, so they
 * also appear under Views and can be shared the same way.
 */
export const FilterBarSavedFilters = observer(function FilterBarSavedFilters(props: TFilterBarSavedFiltersProps) {
  const { filter, workspaceSlug, projectId, appliedViewId, onApply } = props;
  // plane hooks
  const { t } = useTranslation();
  // store hooks
  const { data: currentUser } = useUser();
  const { getProjectViews, getViewById, fetchViews, updateView, addViewToFavorites, removeViewFromFavorites } =
    useProjectView();
  // derived values
  const views = getProjectViews(projectId) ?? [];
  const appliedView = appliedViewId ? getViewById(appliedViewId) : undefined;
  const currentFilters = filter.adapter.toExternal(filter.expression);
  const hasUnsavedChanges = !!appliedView && !isEqual(appliedView.rich_filters ?? {}, currentFilters ?? {});
  const canUpdateApplied = !!appliedView && appliedView.owned_by === currentUser?.id && !appliedView.is_locked;
  const sections: { key: string; views: IProjectView[] }[] = [
    { key: "starred", views: views.filter((view) => view.is_favorite) },
    { key: "mine", views: views.filter((view) => !view.is_favorite && view.owned_by === currentUser?.id) },
    {
      key: "shared",
      views: views.filter(
        (view) => !view.is_favorite && view.owned_by !== currentUser?.id && view.access === EViewAccess.PUBLIC
      ),
    },
  ];

  const toggleStar = (view: IProjectView) =>
    (view.is_favorite
      ? removeViewFromFavorites(workspaceSlug, projectId, view.id)
      : addViewToFavorites(workspaceSlug, projectId, view.id)
    ).catch(() => setToast({ type: TOAST_TYPE.ERROR, title: t("filter_bar.saved.error") }));

  const saveChanges = async () => {
    if (!appliedView) return;
    try {
      await updateView(workspaceSlug, projectId, appliedView.id, { rich_filters: currentFilters });
      setToast({ type: TOAST_TYPE.SUCCESS, title: t("filter_bar.saved.updated", { name: appliedView.name }) });
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("filter_bar.saved.error") });
    }
  };

  return (
    <div className="flex items-center gap-1">
      <FilterBarDropdown
        label={appliedView ? `${t("filter_bar.saved.label")}: ${appliedView.name}` : t("filter_bar.saved.label")}
        isActive={!!appliedView}
        panelClassName="w-72"
        onOpen={() => void fetchViews(workspaceSlug, projectId).catch(() => undefined)}
      >
        {(close) => (
          <div className="vertical-scrollbar scrollbar-sm max-h-80 overflow-y-auto px-2">
            {views.length === 0 && <p className="px-1 py-1.5 text-tertiary">{t("filter_bar.saved.empty")}</p>}
            {sections.map(
              (section) =>
                section.views.length > 0 && (
                  <div key={section.key} className="mb-2">
                    <p className="px-1 pb-1 text-caption-sm-medium text-tertiary">
                      {t(`filter_bar.saved.${section.key}`)}
                    </p>
                    {section.views.map((view) => (
                      <div
                        key={view.id}
                        className={cn("group flex items-center gap-1 rounded-sm hover:bg-layer-1", {
                          "bg-layer-1": view.id === appliedViewId,
                        })}
                      >
                        <button
                          type="button"
                          className="min-w-0 flex-grow truncate px-1 py-1.5 text-left text-secondary"
                          onClick={() => {
                            onApply(view);
                            close();
                          }}
                        >
                          {view.name}
                        </button>
                        <FavoriteStar
                          buttonClassName={cn("mr-1 flex-shrink-0", {
                            "opacity-0 group-hover:opacity-100": !view.is_favorite,
                          })}
                          onClick={(event) => {
                            event.stopPropagation();
                            void toggleStar(view);
                          }}
                          selected={view.is_favorite}
                        />
                      </div>
                    ))}
                  </div>
                )
            )}
            {appliedView && (
              <div className="border-t border-subtle pt-2">
                <button
                  type="button"
                  className="w-full rounded-sm px-1 py-1.5 text-left text-tertiary hover:bg-layer-1 hover:text-secondary"
                  onClick={() => {
                    onApply(null);
                    close();
                  }}
                >
                  {t("filter_bar.saved.close")}
                </button>
              </div>
            )}
          </div>
        )}
      </FilterBarDropdown>
      {hasUnsavedChanges && canUpdateApplied && (
        <button
          type="button"
          className="h-7 rounded-sm border-[0.5px] border-strong px-2 text-caption-md-regular whitespace-nowrap text-secondary hover:bg-layer-1"
          onClick={() => void saveChanges()}
        >
          {t("filter_bar.saved.save_changes")}
        </button>
      )}
      {filter.canSaveView && filter.hasActiveFilters && (
        <button
          type="button"
          className="h-7 rounded-sm border-[0.5px] border-strong px-2 text-caption-md-regular whitespace-nowrap text-secondary hover:bg-layer-1"
          onClick={() => void filter.saveView()}
        >
          {appliedView ? t("filter_bar.saved.save_as") : t("filter_bar.saved.save")}
        </button>
      )}
    </div>
  );
});
