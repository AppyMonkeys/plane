/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// Remembers, per workspace and per browser, the project the user last had open, so pages that
// live outside a project (e.g. the Inbox) can offer a way back to it.

const storageKey = (workspaceSlug: string) => `plane:last-visited-project:${workspaceSlug}`;

export const rememberLastVisitedProject = (workspaceSlug: string, projectId: string): void => {
  try {
    localStorage.setItem(storageKey(workspaceSlug), projectId);
  } catch {
    /* storage unavailable (private mode etc.) -- there is just nothing to go back to */
  }
};

export const getLastVisitedProjectId = (workspaceSlug: string): string | null => {
  try {
    return localStorage.getItem(storageKey(workspaceSlug));
  } catch {
    return null;
  }
};
