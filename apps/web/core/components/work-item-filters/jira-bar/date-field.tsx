/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import type { IWorkItemFilterInstance } from "@plane/shared-state";
import type { TWorkItemFilterProperty } from "@plane/types";
import { cn, renderFormattedDate } from "@plane/utils";
// local imports
import { FilterBarDropdown } from "./dropdown";
import type { TDatePreset } from "./helpers";
import { getDatePresetRange, getDateRange, setDateRange } from "./helpers";

const PAST_PRESETS: TDatePreset[] = ["today", "last_7_days", "last_30_days", "this_month"];
const FUTURE_PRESETS: TDatePreset[] = ["today", "next_7_days", "this_month"];

type TFilterBarDateFieldProps = {
  filter: IWorkItemFilterInstance;
  property: TWorkItemFilterProperty;
  label: string;
  /** Due and start dates are mostly ahead of us; created and updated are behind. */
  isFutureDate?: boolean;
};

/** A date field of the bar (Created, Updated, Due date, ...): a range, from a preset or two dates. */
export const FilterBarDateField = observer(function FilterBarDateField(props: TFilterBarDateFieldProps) {
  const { filter, property, label, isFutureDate = false } = props;
  // plane hooks
  const { t } = useTranslation();
  // derived values
  const [from, to] = getDateRange(filter, property);
  const presets = isFutureDate ? FUTURE_PRESETS : PAST_PRESETS;
  const activePreset = presets.find((preset) => {
    const [presetFrom, presetTo] = getDatePresetRange(preset);
    return presetFrom === from && presetTo === to;
  });
  const summary = activePreset
    ? t(`filter_bar.date.${activePreset}`)
    : from && to
      ? `${renderFormattedDate(from)} – ${renderFormattedDate(to)}`
      : from
        ? t("filter_bar.date.from", { date: renderFormattedDate(from) })
        : to
          ? t("filter_bar.date.until", { date: renderFormattedDate(to) })
          : "";

  return (
    <FilterBarDropdown label={summary ? `${label}: ${summary}` : label} isActive={!!(from || to)}>
      {(close) => (
        <div className="flex flex-col gap-1 px-2">
          {presets.map((preset) => (
            <button
              key={preset}
              type="button"
              className={cn("rounded-sm px-1 py-1.5 text-left text-secondary hover:bg-layer-1", {
                "bg-layer-1 text-primary": preset === activePreset,
              })}
              onClick={() => {
                const [presetFrom, presetTo] = getDatePresetRange(preset);
                setDateRange(filter, property, presetFrom, presetTo);
                close();
              }}
            >
              {t(`filter_bar.date.${preset}`)}
            </button>
          ))}
          <div className="mt-1 grid grid-cols-2 gap-2 border-t border-subtle pt-2">
            <label className="flex flex-col gap-1 text-tertiary">
              {t("filter_bar.date.from_label")}
              <input
                type="date"
                value={from}
                max={to || undefined}
                onChange={(event) => setDateRange(filter, property, event.target.value, to)}
                className="rounded-sm border border-subtle bg-surface-2 px-1.5 py-1 text-secondary"
              />
            </label>
            <label className="flex flex-col gap-1 text-tertiary">
              {t("filter_bar.date.to_label")}
              <input
                type="date"
                value={to}
                min={from || undefined}
                onChange={(event) => setDateRange(filter, property, from, event.target.value)}
                className="rounded-sm border border-subtle bg-surface-2 px-1.5 py-1 text-secondary"
              />
            </label>
          </div>
          {(from || to) && (
            <button
              type="button"
              className="mt-1 rounded-sm px-1 py-1 text-left text-tertiary hover:bg-layer-1 hover:text-secondary"
              onClick={() => {
                setDateRange(filter, property, "", "");
                close();
              }}
            >
              {t("filter_bar.clear_field")}
            </button>
          )}
        </div>
      )}
    </FilterBarDropdown>
  );
});
