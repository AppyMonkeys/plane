/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useState } from "react";
import { sortBy } from "lodash-es";
import { observer } from "mobx-react";
import { Checkbox } from "@makeplane/propel/components/checkbox";
import { SearchOutline } from "@makeplane/propel/icons";
// plane imports
import { useTranslation } from "@plane/i18n";
import type { IWorkItemFilterInstance } from "@plane/shared-state";
import type { IFilterOption, TFilterValue, TWorkItemFilterProperty } from "@plane/types";
import { cn } from "@plane/utils";
// local imports
import { FilterBarDropdown } from "./dropdown";
import { MULTI_SELECT_OPERATOR, getConditionValues, setCondition } from "./helpers";

export type TFilterBarOption = {
  value: string;
  label: string;
  icon?: React.ReactNode;
};

/** The options the filter config of a property offers (states, members, labels, ...), loaded when needed. */
export const useFilterOptions = (filter: IWorkItemFilterInstance, property: TWorkItemFilterProperty) => {
  const [options, setOptions] = useState<TFilterBarOption[]>([]);
  const config = filter.configManager.getConfigByProperty(property);
  const operatorConfig = config?.getOperatorConfig(MULTI_SELECT_OPERATOR);

  const load = useCallback(async () => {
    if (!operatorConfig || !("getOptions" in operatorConfig)) return;
    const { getOptions } = operatorConfig;
    const result: IFilterOption<TFilterValue>[] = typeof getOptions === "function" ? await getOptions() : getOptions;
    setOptions(
      result
        .filter((option) => !option.disabled)
        .map((option) => ({ value: String(option.value), label: String(option.label), icon: option.icon }))
    );
  }, [operatorConfig]);

  useEffect(() => {
    void load().catch(() => undefined);
  }, [load]);

  return { options, reload: load, isAvailable: !!config?.isEnabled && !!operatorConfig };
};

/** Button text: "Status", "Status: Done", or "Status: Done +2". */
export const getFieldLabel = (fieldLabel: string, selectedLabels: string[], allLabel?: string) => {
  if (selectedLabels.length === 0) return allLabel ?? fieldLabel;
  const [first, ...rest] = selectedLabels;
  return `${fieldLabel}: ${first}${rest.length ? ` +${rest.length}` : ""}`;
};

type TOptionsListProps = {
  options: TFilterBarOption[];
  selected: string[];
  onToggle: (value: string) => void;
  searchPlaceholder: string;
  emptyText: string;
  query: string;
  onQueryChange: (query: string) => void;
  isLoading?: boolean;
};

/** Search box + checkbox list, shared by the field dropdowns. */
export function FilterBarOptionsList(props: TOptionsListProps) {
  const { options, selected, onToggle, searchPlaceholder, emptyText, query, onQueryChange, isLoading = false } = props;

  return (
    <>
      <div className="px-2">
        <div className="flex items-center rounded-sm border border-subtle bg-surface-2 px-2">
          <SearchOutline className="h-3.5 w-3.5 flex-shrink-0 text-tertiary" />
          <input
            className="w-full bg-transparent px-2 py-1 text-caption-md-regular text-secondary placeholder:text-placeholder focus:outline-none"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder={searchPlaceholder}
            // oxlint-disable-next-line jsx-a11y/no-autofocus -- like Jira: type straight away to narrow the list
            autoFocus
          />
        </div>
      </div>
      <div className="vertical-scrollbar mt-2 scrollbar-sm max-h-64 overflow-y-auto px-2">
        {options.length === 0 ? (
          <p className="px-1 py-1.5 text-center text-tertiary">{isLoading ? "…" : emptyText}</p>
        ) : (
          options.map((option) => {
            const isSelected = selected.includes(option.value);
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => onToggle(option.value)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-sm px-1 py-1.5 text-left text-secondary hover:bg-layer-1",
                  { "text-primary": isSelected }
                )}
              >
                <Checkbox checked={isSelected} aria-label={option.label} />
                {option.icon && <span className="flex flex-shrink-0 items-center">{option.icon}</span>}
                <span className="truncate">{option.label}</span>
              </button>
            );
          })
        )}
      </div>
    </>
  );
}

type TFilterBarSelectFieldProps = {
  filter: IWorkItemFilterInstance;
  property: TWorkItemFilterProperty;
  label: string;
  /** Options shown above the configured ones, e.g. "Unassigned" or "Current user". */
  extraOptions?: TFilterBarOption[];
};

/** A multi-select field of the bar (Type, Status, Assignee, ...): IN the ticked values. */
export const FilterBarSelectField = observer(function FilterBarSelectField(props: TFilterBarSelectFieldProps) {
  const { filter, property, label, extraOptions = [] } = props;
  // plane hooks
  const { t } = useTranslation();
  // states
  const [query, setQuery] = useState("");
  // derived values
  const { options, reload } = useFilterOptions(filter, property);
  const allOptions = [
    ...extraOptions,
    ...options.filter((option) => !extraOptions.some((e) => e.value === option.value)),
  ];
  const selected = getConditionValues(filter, property);
  const selectedLabels = selected.map(
    (value) => allOptions.find((option) => option.value === value)?.label ?? t("filter_bar.unknown")
  );
  // ticked ones first, like Jira
  const visibleOptions = sortBy(
    allOptions.filter((option) => option.label.toLowerCase().includes(query.trim().toLowerCase())),
    (option) => !selected.includes(option.value)
  );

  const toggle = (value: string) =>
    setCondition(
      filter,
      property,
      MULTI_SELECT_OPERATOR,
      selected.includes(value) ? selected.filter((item) => item !== value) : [...selected, value]
    );

  return (
    <FilterBarDropdown
      label={getFieldLabel(label, selectedLabels)}
      isActive={selected.length > 0}
      onOpen={() => {
        setQuery("");
        void reload().catch(() => undefined);
      }}
    >
      {() => (
        <>
          <FilterBarOptionsList
            options={visibleOptions}
            selected={selected}
            onToggle={toggle}
            searchPlaceholder={t("filter_bar.find", { field: label.toLowerCase() })}
            emptyText={t("filter_bar.no_matches")}
            query={query}
            onQueryChange={setQuery}
          />
          {selected.length > 0 && (
            <div className="mt-2 border-t border-subtle px-2 pt-2">
              <button
                type="button"
                className="w-full rounded-sm px-1 py-1 text-left text-tertiary hover:bg-layer-1 hover:text-secondary"
                onClick={() => setCondition(filter, property, MULTI_SELECT_OPERATOR, null)}
              >
                {t("filter_bar.clear_field")}
              </button>
            </div>
          )}
        </>
      )}
    </FilterBarDropdown>
  );
});
