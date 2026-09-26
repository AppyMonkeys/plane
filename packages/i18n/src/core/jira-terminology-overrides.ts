/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// When VITE_JIRA_TERMINOLOGY="1", these overrides are merged over the English
// resource bundles to relabel "Work item Type" / "State" as Jira-style
// "Work Type" / "Work Status" across the UI.
export const JIRA_TERMINOLOGY_ENABLED = process.env.VITE_JIRA_TERMINOLOGY === "1";

export const JIRA_TERMINOLOGY_OVERRIDES: Record<string, Record<string, unknown>> = {
  common: {
    state: "Work Status",
    common: {
      states: "Work Statuses",
      state: "Work Status",
      state_groups: "Work Status groups",
      state_group: "Work Status group",
    },
  },
  "work-item": {
    issue: {
      display: {
        properties: {
          issue_type: "Work Type",
        },
      },
    },
  },
  "work-item-type": {
    work_item_types: {
      label: "Work Types",
      label_lowercase: "work types",
    },
  },
  "project-settings": {
    project_settings: {
      states: {
        heading: "Work Statuses",
      },
      workflows: {
        create: {
          work_item_type: {
            label: "Work Type",
          },
        },
      },
      features: {
        intake: {
          form: {
            work_item_type: "Work Type",
          },
        },
      },
    },
  },
};
