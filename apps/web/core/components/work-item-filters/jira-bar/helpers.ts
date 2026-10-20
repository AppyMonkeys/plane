/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { IWorkItemFilterInstance } from "@plane/shared-state";
import type { TSupportedOperators, TWorkItemFilterProperty } from "@plane/types";
import { COLLECTION_OPERATOR, COMPARISON_OPERATOR, EQUALITY_OPERATOR, LOGICAL_OPERATOR } from "@plane/types";
import { renderFormattedPayloadDate } from "@plane/utils";

/** Value of the assignee filter that stands for "no assignee" (the server matches it, see IssueFilterSet). */
export const UNASSIGNED = "none";
/** Open-ended bounds of a date range, as the server's JQL translation writes them too. */
export const MIN_DATE = "1970-01-01";
export const MAX_DATE = "9999-12-31";
/** Jira's "unresolved": not done, not cancelled. */
export const OPEN_STATE_GROUPS = ["backlog", "unstarted", "started"];

export const MULTI_SELECT_OPERATOR = COLLECTION_OPERATOR.IN;
export const DATE_RANGE_OPERATOR = COMPARISON_OPERATOR.RANGE;
export const TEXT_OPERATOR = EQUALITY_OPERATOR.EXACT;

/**
 * The filter bar keeps one condition per property, all ANDed: what Jira's basic search can express.
 */
export const getCondition = (filter: IWorkItemFilterInstance, property: TWorkItemFilterProperty) =>
  filter.allConditions.find((condition) => condition.property === property);

export const getConditionValues = (filter: IWorkItemFilterInstance, property: TWorkItemFilterProperty): string[] => {
  const value = getCondition(filter, property)?.value;
  if (value === undefined || value === null || value === "") return [];
  return (Array.isArray(value) ? value : [value]).map(String).filter((item) => item !== "");
};

export const setCondition = (
  filter: IWorkItemFilterInstance,
  property: TWorkItemFilterProperty,
  operator: TSupportedOperators,
  value: string | string[] | null
) => {
  const condition = getCondition(filter, property);
  const isEmpty = value === null || (Array.isArray(value) ? value.length === 0 : value.trim() === "");
  if (condition && (isEmpty || condition.operator !== operator)) filter.removeCondition(condition.id);
  if (isEmpty) return;
  if (condition && condition.operator === operator) filter.updateConditionValue(condition.id, value);
  else filter.addCondition(LOGICAL_OPERATOR.AND, { property, operator, value }, false);
};

export const sameValues = (a: string[], b: string[]) => a.length === b.length && a.every((value) => b.includes(value));

// ------------ dates ------------

export type TDatePreset = "today" | "last_7_days" | "last_30_days" | "this_month" | "next_7_days";

const daysFromToday = (days: number) => {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return renderFormattedPayloadDate(date) ?? "";
};

export const getDatePresetRange = (preset: TDatePreset): [string, string] => {
  const today = daysFromToday(0);
  if (preset === "today") return [today, today];
  if (preset === "last_7_days") return [daysFromToday(-7), today];
  if (preset === "last_30_days") return [daysFromToday(-30), today];
  if (preset === "next_7_days") return [today, daysFromToday(7)];
  const firstOfMonth = new Date();
  firstOfMonth.setDate(1);
  return [renderFormattedPayloadDate(firstOfMonth) ?? today, today];
};

/** The [from, to] of a date property's range condition, with open ends as "". */
export const getDateRange = (filter: IWorkItemFilterInstance, property: TWorkItemFilterProperty): [string, string] => {
  const condition = getCondition(filter, property);
  if (!condition) return ["", ""];
  const values = getConditionValues(filter, property);
  if (condition.operator !== DATE_RANGE_OPERATOR) return [values[0] ?? "", values[0] ?? ""];
  const [from = "", to = ""] = values;
  return [from === MIN_DATE ? "" : from, to === MAX_DATE ? "" : to];
};

export const setDateRange = (
  filter: IWorkItemFilterInstance,
  property: TWorkItemFilterProperty,
  from: string,
  to: string
) => setCondition(filter, property, DATE_RANGE_OPERATOR, from || to ? [from || MIN_DATE, to || MAX_DATE] : null);
