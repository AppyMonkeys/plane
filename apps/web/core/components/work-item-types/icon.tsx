/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TLogoProps } from "@plane/types";
import { cn } from "@plane/utils";
// local imports
import { WORK_ITEM_TYPE_COLORS, WORK_ITEM_TYPE_FALLBACK_ICON, WORK_ITEM_TYPE_ICONS } from "./constants";

type TWorkItemTypeIconProps = {
  logoProps: TLogoProps | undefined | null;
  /** Side of the coloured square, in px */
  size?: number;
  className?: string;
};

/**
 * The small coloured square with a glyph that identifies a work item type (Task, Bug, Story, ...).
 */
export function WorkItemTypeIcon(props: TWorkItemTypeIconProps) {
  const { logoProps, size = 16, className } = props;
  const Icon = WORK_ITEM_TYPE_ICONS[logoProps?.icon?.name ?? ""] ?? WORK_ITEM_TYPE_FALLBACK_ICON;
  const glyphSize = Math.round(size * 0.7);

  return (
    <span
      className={cn("grid flex-shrink-0 place-items-center rounded-sm", className)}
      style={{
        width: size,
        height: size,
        backgroundColor: logoProps?.icon?.background_color ?? WORK_ITEM_TYPE_COLORS[0],
      }}
    >
      <Icon
        width={glyphSize}
        height={glyphSize}
        strokeWidth={2.75}
        style={{ color: logoProps?.icon?.color ?? "#ffffff" }}
      />
    </span>
  );
}
