/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TIssue } from "./issues/issue";

/** The work item fields a template fills in when someone starts a work item from it. */
export type TWorkItemTemplateData = Partial<
  Pick<
    TIssue,
    "name" | "description_html" | "type_id" | "priority" | "state_id" | "label_ids" | "assignee_ids" | "module_ids"
  >
>;

export type TWorkItemTemplate = {
  id: string;
  name: string;
  template_data: TWorkItemTemplateData;
  project_id: string;
  workspace_id: string;
  created_by: string;
  created_at?: string;
  updated_at?: string;
};
