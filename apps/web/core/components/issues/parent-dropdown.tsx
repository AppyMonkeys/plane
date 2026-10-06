/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { usePopper } from "react-popper";
import { SearchOutline } from "@makeplane/propel/icons";
import { Combobox } from "@headlessui/react";
// plane imports
import { useTranslation } from "@plane/i18n";
import type { ISearchIssueResponse } from "@plane/types";
import { cn } from "@plane/utils";
// components
import { IssueIdentifier } from "@/components/issues/issue-detail/issue-identifier";
// hooks
import useDebounce from "@/hooks/use-debounce";
// services
import { ProjectService } from "@/services/project";

const projectService = new ProjectService();

type TParentDropdownProps = {
  workspaceSlug: string;
  projectId: string;
  /** The work item getting a parent, when it already exists (keeps itself and its children out of the list). */
  issueId?: string;
  onChange: (issue: ISearchIssueResponse) => void;
  /** What the trigger button shows. */
  button: React.ReactNode;
  buttonClassName?: string;
  disabled?: boolean;
};

/**
 * Picks a parent work item the way assignees and labels are picked: a dropdown under the button
 * with a search box that filters as you type. Candidates come from the server (see the
 * search-issues endpoint), so the list is whatever that offers as parents -- epics, on projects
 * that have them.
 */
export function ParentDropdown(props: TParentDropdownProps) {
  const { workspaceSlug, projectId, issueId, onChange, button, buttonClassName, disabled = false } = props;
  // plane hooks
  const { t } = useTranslation();
  // states
  const [referenceElement, setReferenceElement] = useState<HTMLButtonElement | null>(null);
  const [popperElement, setPopperElement] = useState<HTMLDivElement | null>(null);
  const [isActive, setIsActive] = useState(false);
  const [query, setQuery] = useState("");
  const [issues, setIssues] = useState<ISearchIssueResponse[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const debouncedQuery: string = useDebounce(query, 300);

  const { styles, attributes } = usePopper(referenceElement, popperElement, {
    placement: "bottom-start",
    modifiers: [{ name: "preventOverflow", options: { padding: 12 } }],
  });

  // search once the dropdown has been opened, and again as the text changes
  useEffect(() => {
    if (!isActive || !workspaceSlug || !projectId) return;
    let isCurrent = true;
    setIsLoading(true);
    projectService
      .projectIssuesSearch(workspaceSlug, projectId, {
        search: debouncedQuery,
        parent: true,
        issue_id: issueId,
        workspace_search: false,
      })
      .then((response) => {
        if (isCurrent) setIssues(response ?? []);
        return undefined;
      })
      .catch(() => {
        if (isCurrent) setIssues([]);
      })
      .finally(() => {
        if (isCurrent) setIsLoading(false);
      });
    return () => {
      isCurrent = false;
    };
  }, [isActive, debouncedQuery, workspaceSlug, projectId, issueId]);

  return (
    <Combobox
      as="div"
      className="h-full flex-shrink-0 text-left"
      value={null}
      onChange={(issue: ISearchIssueResponse | null) => {
        if (!issue) return;
        onChange(issue);
        setQuery("");
      }}
      disabled={disabled}
    >
      <Combobox.Button
        ref={setReferenceElement}
        type="button"
        className={buttonClassName}
        onClick={() => setIsActive(true)}
      >
        {button}
      </Combobox.Button>

      <Combobox.Options modal={false} as="ul" className="fixed z-10">
        <div
          className="z-10 my-1 w-72 rounded-sm border border-strong bg-surface-1 py-2.5 text-11 shadow-raised-200 focus:outline-none"
          ref={setPopperElement}
          style={styles.popper}
          {...attributes.popper}
        >
          <div className="px-2">
            <div className="flex w-full items-center justify-start rounded-sm border border-subtle bg-surface-2 px-2">
              <SearchOutline className="h-3.5 w-3.5 flex-shrink-0 text-tertiary" />
              <Combobox.Input
                className="w-full bg-transparent px-2 py-1 text-11 text-secondary placeholder:text-placeholder focus:outline-none"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("common.search.label")}
                displayValue={() => query}
                onKeyDown={(event) => {
                  // first Escape clears the text, the next one closes the dropdown
                  if (query !== "" && event.key === "Escape") {
                    event.stopPropagation();
                    setQuery("");
                  }
                }}
                // oxlint-disable-next-line jsx-a11y/no-autofocus -- same as the assignee and label dropdowns: type straight away
                autoFocus
              />
            </div>
          </div>
          <div className="vertical-scrollbar mt-2 scrollbar-sm max-h-56 overflow-y-scroll px-2 pr-0">
            {issues.length > 0 ? (
              <ul className={cn("space-y-1", { "opacity-60": isLoading })}>
                {issues.map((issue) => (
                  <Combobox.Option
                    as="li"
                    key={issue.id}
                    value={issue}
                    className={({ active }) =>
                      cn("flex cursor-pointer items-center gap-2 rounded-sm px-1 py-1.5 text-secondary select-none", {
                        "bg-layer-1 text-primary": active,
                      })
                    }
                  >
                    <span className="flex-shrink-0">
                      <IssueIdentifier
                        projectId={issue.project_id}
                        issueTypeId={issue.type_id}
                        projectIdentifier={issue.project__identifier}
                        issueSequenceId={issue.sequence_id}
                        size="xs"
                        variant="secondary"
                      />
                    </span>
                    <span className="truncate">{issue.name}</span>
                  </Combobox.Option>
                ))}
              </ul>
            ) : (
              <p className="px-1 py-1.5 text-center text-tertiary">
                {isLoading ? t("common.loading") : t("issue.no_matching_parent")}
              </p>
            )}
          </div>
        </div>
      </Combobox.Options>
    </Combobox>
  );
}
