/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TIssue, TWorkItemTemplateData } from "@plane/types";

/** The fields of the create form that a template saves. */
export const getTemplateDataFromForm = (values: Partial<TIssue>): TWorkItemTemplateData => ({
  name: values.name || undefined,
  description_html: values.description_html || undefined,
  type_id: values.type_id || undefined,
  priority: values.priority || undefined,
  state_id: values.state_id || undefined,
  label_ids: values.label_ids?.length ? values.label_ids : undefined,
  assignee_ids: values.assignee_ids?.length ? values.assignee_ids : undefined,
  module_ids: values.module_ids?.length ? values.module_ids : undefined,
});

type TProjectEntities = {
  stateIds: string[];
  typeIds: string[];
  labelIds: string[];
  memberIds: string[];
  moduleIds: string[];
};

const keepAllowed = (ids: string[] | null | undefined, allowed: string[]) =>
  (ids ?? []).filter((id) => allowed.includes(id));

/**
 * A template's fields, minus anything the project no longer has (a deleted state or label, a member
 * who left), so applying an old template never fills in values the form can't show or save.
 */
export const getApplicableTemplateData = (
  data: TWorkItemTemplateData,
  entities: TProjectEntities
): TWorkItemTemplateData => {
  return {
    ...data,
    type_id: data.type_id && entities.typeIds.includes(data.type_id) ? data.type_id : undefined,
    state_id: data.state_id && entities.stateIds.includes(data.state_id) ? data.state_id : undefined,
    label_ids: keepAllowed(data.label_ids, entities.labelIds),
    assignee_ids: keepAllowed(data.assignee_ids, entities.memberIds),
    module_ids: keepAllowed(data.module_ids, entities.moduleIds),
  };
};
