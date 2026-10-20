/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import type { IWorkItemFilterInstance } from "@plane/shared-state";
import type { ISearchIssueResponse } from "@plane/types";
// hooks
import useDebounce from "@/hooks/use-debounce";
// services
import { ProjectService } from "@/services/project";
// local imports
import { FilterBarDropdown } from "./dropdown";
import { MULTI_SELECT_OPERATOR, getConditionValues, setCondition } from "./helpers";
import type { TFilterBarOption } from "./select-field";
import { FilterBarOptionsList, getFieldLabel } from "./select-field";

const projectService = new ProjectService();

const toOption = (issue: ISearchIssueResponse): TFilterBarOption => ({
  value: issue.id,
  label: `${issue.project__identifier}-${issue.sequence_id} ${issue.name}`,
});

type TFilterBarParentFieldProps = {
  filter: IWorkItemFilterInstance;
  workspaceSlug: string;
  projectId: string;
  label: string;
};

/** Parent (Epic Link in Jira): work items under the ticked epics. Searches the server as you type. */
export const FilterBarParentField = observer(function FilterBarParentField(props: TFilterBarParentFieldProps) {
  const { filter, workspaceSlug, projectId, label } = props;
  // plane hooks
  const { t } = useTranslation();
  // states
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<TFilterBarOption[]>([]);
  // labels of parents seen in search results, for the button text
  const [known, setKnown] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(false);
  const debouncedQuery: string = useDebounce(query, 300);
  // derived values
  const selected = getConditionValues(filter, "parent_id");

  useEffect(() => {
    if (!isOpen) return;
    let isCurrent = true;
    setIsLoading(true);
    projectService
      .projectIssuesSearch(workspaceSlug, projectId, { search: debouncedQuery, parent: true, workspace_search: false })
      .then((response) => {
        if (!isCurrent) return undefined;
        const options = (response ?? []).map(toOption);
        setResults(options);
        setKnown((current) => ({ ...current, ...Object.fromEntries(options.map((o) => [o.value, o.label])) }));
        return undefined;
      })
      .catch(() => isCurrent && setResults([]))
      .finally(() => isCurrent && setIsLoading(false));
    return () => {
      isCurrent = false;
    };
  }, [isOpen, debouncedQuery, workspaceSlug, projectId]);

  const selectedOptions = selected.map((value) => ({ value, label: known[value] ?? t("filter_bar.unknown") }));
  const options = [...selectedOptions, ...results.filter((option) => !selected.includes(option.value))];

  return (
    <FilterBarDropdown
      label={getFieldLabel(
        label,
        selectedOptions.map((option) => option.label.split(" ")[0])
      )}
      isActive={selected.length > 0}
      panelClassName="w-80"
      onOpen={() => {
        setQuery("");
        setIsOpen(true);
      }}
    >
      {() => (
        <FilterBarOptionsList
          options={options}
          selected={selected}
          onToggle={(value) =>
            setCondition(
              filter,
              "parent_id",
              MULTI_SELECT_OPERATOR,
              selected.includes(value) ? selected.filter((item) => item !== value) : [...selected, value]
            )
          }
          searchPlaceholder={t("filter_bar.find", { field: label.toLowerCase() })}
          emptyText={t("filter_bar.no_matches")}
          query={query}
          onQueryChange={setQuery}
          isLoading={isLoading}
        />
      )}
    </FilterBarDropdown>
  );
});
