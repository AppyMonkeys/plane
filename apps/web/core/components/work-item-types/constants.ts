/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import {
  Bookmark,
  Bug,
  Check,
  Circle,
  Database,
  FileText,
  Flag,
  FlaskConical,
  HelpCircle,
  Lightbulb,
  ListTree,
  Palette,
  Plus,
  Rocket,
  Search,
  Shield,
  Star,
  TrendingUp,
  Wrench,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { TLogoProps } from "@plane/types";

// Icons a work item type can use, keyed by the name stored in `logo_props.icon.name`.
export const WORK_ITEM_TYPE_ICONS: Record<string, LucideIcon> = {
  Check,
  Bug,
  Bookmark,
  Zap,
  ListTree,
  TrendingUp,
  Plus,
  Lightbulb,
  Flag,
  Wrench,
  FlaskConical,
  FileText,
  HelpCircle,
  Rocket,
  Shield,
  Star,
  Palette,
  Database,
  Search,
  Circle,
};

export const WORK_ITEM_TYPE_FALLBACK_ICON = Circle;

export const WORK_ITEM_TYPE_COLORS = [
  "#4bade8",
  "#e5493a",
  "#63ba3c",
  "#904ee2",
  "#f79232",
  "#f5c400",
  "#00a3bf",
  "#d6409f",
  "#6b7280",
  "#1f2937",
];

export const DEFAULT_WORK_ITEM_TYPE_LOGO: TLogoProps = {
  in_use: "icon",
  icon: { name: "Check", color: "#ffffff", background_color: WORK_ITEM_TYPE_COLORS[0] },
};
