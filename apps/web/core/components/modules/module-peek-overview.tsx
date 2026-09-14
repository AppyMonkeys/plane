/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

type Props = {
  projectId: string;
  workspaceSlug: string;
  isArchived?: boolean;
};

// The module peek overview panel previously rendered the module analytics/progress-stats
// sidebar (removed along with the in-app Analytics dashboard feature). It is kept as a
// no-op so existing callers passing `peekModule`/props do not need to change.
export const ModulePeekOverview = (_props: Props) => null;
