/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import * as React from "react";
import {
  AlertCircle,
  Ban,
  ChevronDown,
  ChevronsDown,
  ChevronsUp,
  ChevronUp,
  Equal,
  SignalHigh,
  SignalLow,
  SignalMedium,
} from "lucide-react";
import { IS_JIRA_PRIORITY_ENABLED } from "@plane/constants";
import { cn } from "../utils";

export type TIssuePriorities = "urgent" | "high" | "medium" | "low" | "none";

interface IPriorityIcon {
  className?: string;
  containerClassName?: string;
  priority: TIssuePriorities | undefined | null;
  size?: number;
  withContainer?: boolean;
}

// Jira-style arrows: Highest/High point up, Medium is "=", Low/Lowest point down
const JIRA_ICONS = {
  urgent: ChevronsUp,
  high: ChevronUp,
  medium: Equal,
  low: ChevronDown,
  none: ChevronsDown,
};

const PLANE_ICONS = {
  urgent: AlertCircle,
  high: SignalHigh,
  medium: SignalMedium,
  low: SignalLow,
  none: Ban,
};

export function PriorityIcon(props: IPriorityIcon) {
  const { priority, className = "", containerClassName = "", size = 14, withContainer = false } = props;

  const priorityClasses = {
    urgent: "bg-layer-2 text-priority-urgent border-priority-urgent",
    high: "bg-layer-2 text-priority-high border-priority-high",
    medium: "bg-layer-2 text-priority-medium border-priority-medium",
    low: "bg-layer-2 text-priority-low border-priority-low",
    // "none" is shown as "Lowest" in Jira mode, so color it like Low
    none: IS_JIRA_PRIORITY_ENABLED
      ? "bg-layer-2 text-priority-low border-priority-low"
      : "bg-layer-2 text-priority-none border-priority-none",
  };

  // get priority icon
  const icons = IS_JIRA_PRIORITY_ENABLED ? JIRA_ICONS : PLANE_ICONS;
  const Icon = icons[priority ?? "none"];

  if (!Icon) return null;

  return (
    <>
      {withContainer ? (
        <div
          className={cn(
            "flex flex-shrink-0 items-center justify-center rounded-sm border p-0.5",
            priorityClasses[priority ?? "none"],
            containerClassName
          )}
        >
          <Icon
            size={size}
            className={cn(
              !IS_JIRA_PRIORITY_ENABLED && {
                "translate-x-[0.0625rem]": priority === "high",
                "translate-x-0.5": priority === "medium",
                "translate-x-1": priority === "low",
              },
              className
            )}
          />
        </div>
      ) : (
        <Icon
          size={size}
          className={cn(
            "flex-shrink-0",
            {
              "text-priority-urgent": priority === "urgent",
              "text-priority-high": priority === "high",
              "text-priority-medium": priority === "medium",
              "text-priority-low": priority === "low" || (IS_JIRA_PRIORITY_ENABLED && priority === "none"),
              "text-priority-none": !IS_JIRA_PRIORITY_ENABLED && priority === "none",
            },
            className
          )}
        />
      )}
    </>
  );
}
