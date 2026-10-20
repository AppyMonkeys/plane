/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import { observer } from "mobx-react";
import { SearchOutline } from "@makeplane/propel/icons";
// plane imports
import { EIssueFilterType, IS_CYCLES_MODULES_HIDDEN } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import type { IWorkItemFilterInstance } from "@plane/shared-state";
import type { IProjectView, TIssueOrderByOptions, TWorkItemFilterProperty } from "@plane/types";
import { EIssuesStoreType } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useIssues } from "@/hooks/store/use-issues";
import { useProject } from "@/hooks/store/use-project";
import { useUser } from "@/hooks/store/user";
import { useWorkItemType } from "@/hooks/store/use-work-item-type";
import useDebounce from "@/hooks/use-debounce";
// services
import { JQLService } from "@/services/issue";
// local imports
import { FilterBarDateField } from "./date-field";
import { FilterBarDropdown } from "./dropdown";
import {
  DATE_RANGE_OPERATOR,
  MULTI_SELECT_OPERATOR,
  OPEN_STATE_GROUPS,
  TEXT_OPERATOR,
  UNASSIGNED,
  getCondition,
  getConditionValues,
  getDatePresetRange,
  getDateRange,
  sameValues,
  setCondition,
  setDateRange,
} from "./helpers";
import { FilterBarJQLInput } from "./jql-input";
import { FilterBarParentField } from "./parent-field";
import { FilterBarSavedFilters } from "./saved-filters";
import { FilterBarSelectField } from "./select-field";

const jqlService = new JQLService();

type TMoreField = {
  property: TWorkItemFilterProperty;
  labelKey: string;
  kind: "select" | "date" | "parent";
  isFutureDate?: boolean;
};

// the "+ More" fields, in Jira's order
const MORE_FIELDS: TMoreField[] = [
  { property: "created_by_id", labelKey: "filter_bar.fields.reporter", kind: "select" },
  { property: "created_at", labelKey: "filter_bar.fields.created", kind: "date" },
  { property: "updated_at", labelKey: "filter_bar.fields.updated", kind: "date" },
  { property: "target_date", labelKey: "filter_bar.fields.due_date", kind: "date", isFutureDate: true },
  { property: "start_date", labelKey: "filter_bar.fields.start_date", kind: "date", isFutureDate: true },
  { property: "parent_id", labelKey: "filter_bar.fields.parent", kind: "parent" },
  { property: "cycle_id", labelKey: "filter_bar.fields.cycle", kind: "select" },
  { property: "module_id", labelKey: "filter_bar.fields.module", kind: "select" },
  { property: "state_group", labelKey: "filter_bar.fields.status_category", kind: "select" },
];

const storageKey = (projectId: string, name: string) => `plane:filter-bar:${name}:${projectId}`;

const readStorage = <T,>(key: string, fallback: T): T => {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
};

const writeStorage = (key: string, value: unknown) => {
  try {
    if (value === null || value === undefined) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // private mode or blocked storage: the bar still works, it just won't remember
  }
};

type TJiraFilterBarProps = {
  filter: IWorkItemFilterInstance;
  workspaceSlug: string;
  projectId: string;
};

/**
 * Jira-style filters above a project's work items: a search box, a button per field, quick filters,
 * saved filters and a JQL mode. Everything edits the same filter expression the rest of Plane uses.
 */
export const JiraFilterBar = observer(function JiraFilterBar(props: TJiraFilterBarProps) {
  const { filter, workspaceSlug, projectId } = props;
  // plane hooks
  const { t } = useTranslation();
  // store hooks
  const { data: currentUser } = useUser();
  const { getProjectById } = useProject();
  const { isWorkItemTypeEnabledForProject } = useWorkItemType();
  const { issuesFilter } = useIssues(EIssuesStoreType.PROJECT);
  // states
  const [mode, setMode] = useState<"basic" | "jql">(() => readStorage(storageKey(projectId, "mode"), "basic"));
  const [addedFields, setAddedFields] = useState<TWorkItemFilterProperty[]>(() =>
    readStorage(storageKey(projectId, "fields"), [])
  );
  const [appliedViewId, setAppliedViewId] = useState<string | null>(() =>
    readStorage(storageKey(projectId, "view"), null)
  );
  const [jql, setJql] = useState("");
  const [searchText, setSearchText] = useState(() => getConditionValues(filter, "text")[0] ?? "");
  const debouncedSearchText: string = useDebounce(searchText, 400);
  const lastAppliedSearch = useRef(searchText);
  // derived values
  const project = getProjectById(projectId);
  const currentUserId = currentUser?.id ?? "";
  const textCondition = getConditionValues(filter, "text")[0] ?? "";
  const assignees = getConditionValues(filter, "assignee_id");
  const stateGroups = getConditionValues(filter, "state_group");
  const [updatedFrom, updatedTo] = getDateRange(filter, "updated_at");
  const [weekAgo, today] = getDatePresetRange("last_7_days");
  const orderBy = issuesFilter.issueFilters?.displayFilters?.order_by;
  const moreFields = MORE_FIELDS.filter((field) => {
    if (field.property === "cycle_id") return !IS_CYCLES_MODULES_HIDDEN && !!project?.cycle_view;
    if (field.property === "module_id") return !IS_CYCLES_MODULES_HIDDEN && !!project?.module_view;
    return true;
  });
  const visibleMoreFields = moreFields.filter(
    (field) => addedFields.includes(field.property) || !!getCondition(filter, field.property)
  );

  useEffect(() => writeStorage(storageKey(projectId, "mode"), mode), [projectId, mode]);
  useEffect(() => writeStorage(storageKey(projectId, "fields"), addedFields), [projectId, addedFields]);
  useEffect(() => writeStorage(storageKey(projectId, "view"), appliedViewId), [projectId, appliedViewId]);

  // typing in the search box filters after a pause
  useEffect(() => {
    if (debouncedSearchText === lastAppliedSearch.current) return;
    lastAppliedSearch.current = debouncedSearchText;
    setCondition(filter, "text", TEXT_OPERATOR, debouncedSearchText.trim() || null);
  }, [debouncedSearchText, filter]);

  // and follows the filter when something else changes it (JQL, a saved filter, Clear)
  useEffect(() => {
    if (textCondition === lastAppliedSearch.current.trim()) return;
    lastAppliedSearch.current = textCondition;
    setSearchText(textCondition);
  }, [textCondition]);

  const quickFilters = [
    {
      key: "mine",
      isActive: !!currentUserId && sameValues(assignees, [currentUserId]),
      apply: (on: boolean) => setCondition(filter, "assignee_id", MULTI_SELECT_OPERATOR, on ? [currentUserId] : null),
    },
    {
      key: "recently_updated",
      isActive: updatedFrom === weekAgo && (updatedTo === today || updatedTo === ""),
      apply: (on: boolean) => setDateRange(filter, "updated_at", on ? weekAgo : "", on ? today : ""),
    },
    {
      key: "unassigned",
      isActive: sameValues(assignees, [UNASSIGNED]),
      apply: (on: boolean) => setCondition(filter, "assignee_id", MULTI_SELECT_OPERATOR, on ? [UNASSIGNED] : null),
    },
    {
      key: "open",
      isActive: sameValues(stateGroups, OPEN_STATE_GROUPS),
      apply: (on: boolean) => setCondition(filter, "state_group", MULTI_SELECT_OPERATOR, on ? OPEN_STATE_GROUPS : null),
    },
  ];

  const applyOrderBy = (value: TIssueOrderByOptions | null | undefined) => {
    if (!value || value === orderBy) return;
    void issuesFilter.updateFilters(workspaceSlug, projectId, EIssueFilterType.DISPLAY_FILTERS, { order_by: value });
  };

  const switchMode = async (next: "basic" | "jql") => {
    if (next === mode) return;
    if (next === "jql") {
      try {
        setJql(
          await jqlService.format(workspaceSlug, projectId, filter.adapter.toExternal(filter.expression), orderBy)
        );
      } catch {
        setJql("");
      }
    }
    setMode(next);
  };

  const runJQL = async (value: string) => {
    const response = await jqlService.parse(workspaceSlug, projectId, value);
    filter.resetExpression(response.filters);
    applyOrderBy(response.order_by);
    setAppliedViewId(null);
    return response;
  };

  const applySavedFilter = (view: IProjectView | null) => {
    setAppliedViewId(view?.id ?? null);
    if (!view) return;
    filter.resetExpression(view.rich_filters ?? {});
    applyOrderBy(view.display_filters?.order_by);
    if (mode === "jql")
      void jqlService
        .format(workspaceSlug, projectId, view.rich_filters ?? {}, view.display_filters?.order_by ?? orderBy)
        .then(setJql)
        .catch(() => setJql(""));
  };

  const modeSwitch = (
    <div className="flex h-7 flex-shrink-0 items-center rounded-sm border-[0.5px] border-strong p-0.5">
      {(["basic", "jql"] as const).map((item) => (
        <button
          key={item}
          type="button"
          onClick={() => void switchMode(item)}
          className={cn("h-full rounded-sm px-2 text-caption-md-regular", {
            "bg-layer-1 text-primary": mode === item,
            "text-tertiary hover:text-secondary": mode !== item,
          })}
        >
          {t(`filter_bar.mode.${item}`)}
        </button>
      ))}
    </div>
  );

  return (
    <div className="flex flex-col gap-2 border-b border-subtle bg-surface-1 px-page-x py-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        {mode === "jql" ? (
          <FilterBarJQLInput value={jql} onChange={setJql} onSearch={runJQL} />
        ) : (
          <>
            <div className="flex h-7 w-52 flex-shrink-0 items-center rounded-sm border-[0.5px] border-strong px-2 focus-within:border-accent-strong">
              <SearchOutline className="h-3.5 w-3.5 flex-shrink-0 text-tertiary" />
              <input
                className="w-full bg-transparent px-2 text-caption-md-regular text-primary placeholder:text-placeholder focus:outline-none"
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
                placeholder={t("filter_bar.search")}
                aria-label={t("filter_bar.search")}
              />
            </div>
            {isWorkItemTypeEnabledForProject(projectId) && (
              <FilterBarSelectField filter={filter} property="type_id" label={t("filter_bar.fields.type")} />
            )}
            <FilterBarSelectField filter={filter} property="state_id" label={t("filter_bar.fields.status")} />
            <FilterBarSelectField
              filter={filter}
              property="assignee_id"
              label={t("filter_bar.fields.assignee")}
              extraOptions={[{ value: UNASSIGNED, label: t("filter_bar.unassigned") }]}
            />
            <FilterBarSelectField filter={filter} property="priority" label={t("filter_bar.fields.priority")} />
            <FilterBarSelectField filter={filter} property="label_id" label={t("filter_bar.fields.labels")} />
            {visibleMoreFields.map((field) =>
              field.kind === "date" ? (
                <FilterBarDateField
                  key={field.property}
                  filter={filter}
                  property={field.property}
                  label={t(field.labelKey)}
                  isFutureDate={field.isFutureDate}
                />
              ) : field.kind === "parent" ? (
                <FilterBarParentField
                  key={field.property}
                  filter={filter}
                  workspaceSlug={workspaceSlug}
                  projectId={projectId}
                  label={t(field.labelKey)}
                />
              ) : (
                <FilterBarSelectField
                  key={field.property}
                  filter={filter}
                  property={field.property}
                  label={t(field.labelKey)}
                />
              )
            )}
            <FilterBarDropdown label={`+ ${t("filter_bar.more")}`} hideChevron panelClassName="w-56">
              {() => (
                <div className="px-2">
                  {moreFields.map((field) => {
                    const isShown = visibleMoreFields.includes(field);
                    return (
                      <button
                        key={field.property}
                        type="button"
                        className={cn(
                          "flex w-full items-center justify-between rounded-sm px-1 py-1.5 text-left text-secondary hover:bg-layer-1",
                          { "text-primary": isShown }
                        )}
                        onClick={() => {
                          if (!isShown) {
                            setAddedFields((current) => [...current, field.property]);
                            return;
                          }
                          // taking a field away also drops its filter, as in Jira
                          setAddedFields((current) => current.filter((property) => property !== field.property));
                          setCondition(
                            filter,
                            field.property,
                            field.kind === "date" ? DATE_RANGE_OPERATOR : MULTI_SELECT_OPERATOR,
                            null
                          );
                        }}
                      >
                        {t(field.labelKey)}
                        {isShown && <span className="text-accent-primary">✓</span>}
                      </button>
                    );
                  })}
                </div>
              )}
            </FilterBarDropdown>
          </>
        )}
        {modeSwitch}
        <FilterBarSavedFilters
          filter={filter}
          workspaceSlug={workspaceSlug}
          projectId={projectId}
          appliedViewId={appliedViewId}
          onApply={applySavedFilter}
        />
        {filter.hasActiveFilters && (
          <button
            type="button"
            className="h-7 px-1 text-caption-md-regular text-tertiary hover:text-secondary"
            onClick={() => {
              setAppliedViewId(null);
              filter.resetExpression({});
              if (mode === "jql") setJql("");
            }}
          >
            {t("filter_bar.clear")}
          </button>
        )}
      </div>
      {mode === "basic" && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-caption-sm-medium text-tertiary">{t("filter_bar.quick.label")}</span>
          {quickFilters.map((quickFilter) => (
            <button
              key={quickFilter.key}
              type="button"
              aria-pressed={quickFilter.isActive}
              onClick={() => quickFilter.apply(!quickFilter.isActive)}
              className={cn("h-6 rounded-full border-[0.5px] px-2.5 text-caption-sm-regular", {
                "border-accent-strong bg-accent-subtle text-accent-primary": quickFilter.isActive,
                "border-strong text-secondary hover:bg-layer-1": !quickFilter.isActive,
              })}
            >
              {t(`filter_bar.quick.${quickFilter.key}`)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
});
