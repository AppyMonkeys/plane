/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { SearchOutline } from "@makeplane/propel/icons";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import type { TJQLParseResponse } from "@/services/issue";

type TFilterBarJQLInputProps = {
  value: string;
  onChange: (value: string) => void;
  onSearch: (jql: string) => Promise<TJQLParseResponse | void>;
};

/** Jira's advanced search: one JQL line, run with Enter or the Search button. */
export const FilterBarJQLInput = observer(function FilterBarJQLInput(props: TFilterBarJQLInputProps) {
  const { value, onChange, onSearch } = props;
  // plane hooks
  const { t } = useTranslation();
  // states
  const [error, setError] = useState<string | null>(null);
  const [isSearching, setIsSearching] = useState(false);

  const search = async () => {
    setIsSearching(true);
    setError(null);
    try {
      await onSearch(value);
    } catch (searchError) {
      setError((searchError as { error?: string } | undefined)?.error ?? t("filter_bar.jql.error"));
    } finally {
      setIsSearching(false);
    }
  };

  return (
    <div className="flex min-w-0 flex-grow flex-col gap-1">
      <div className="flex items-center gap-2">
        <div className="flex min-w-0 flex-grow items-center rounded-sm border-[0.5px] border-strong bg-surface-1 px-2 focus-within:border-accent-strong">
          <SearchOutline className="h-3.5 w-3.5 flex-shrink-0 text-tertiary" />
          <input
            className="font-mono h-7 w-full bg-transparent px-2 text-caption-md-regular text-primary placeholder:text-placeholder focus:outline-none"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void search();
              }
            }}
            placeholder={t("filter_bar.jql.placeholder")}
            spellCheck={false}
            aria-label={t("filter_bar.jql.label")}
          />
        </div>
        <Button variant="primary" size="sm" onClick={() => void search()} loading={isSearching}>
          {t("filter_bar.jql.search")}
        </Button>
      </div>
      {error && <p className="text-caption-sm-regular text-danger-primary">{error}</p>}
    </div>
  );
});
