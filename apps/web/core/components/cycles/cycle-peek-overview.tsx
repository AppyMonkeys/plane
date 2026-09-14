/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

type Props = {
  projectId?: string;
  workspaceSlug: string;
  isArchived?: boolean;
};

// The cycle peek overview panel previously rendered the cycle analytics/progress-stats
// sidebar (removed along with the in-app Analytics dashboard feature). It is kept as a
// no-op so existing callers passing `peekCycle`/props do not need to change.
export const CyclePeekOverview = (_props: Props) => null;
