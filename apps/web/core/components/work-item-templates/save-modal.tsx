/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { Input, InputGroup } from "@makeplane/propel/components/input";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TWorkItemTemplate, TWorkItemTemplateData } from "@plane/types";
import { EModalPosition, EModalWidth, ModalCore } from "@plane/ui";
// hooks
import { useWorkItemTemplate } from "@/hooks/store/use-work-item-template";

type TSaveWorkItemTemplateModalProps = {
  isOpen: boolean;
  onClose: () => void;
  workspaceSlug: string;
  projectId: string;
  /** The fields to save. Leave out to only rename `template`. */
  data?: TWorkItemTemplateData;
  /** Rename this template instead of creating a new one. */
  template?: TWorkItemTemplate;
  onSaved?: (template: TWorkItemTemplate) => void;
};

/** Asks for a name, then saves the given fields as a template of the project. */
export function SaveWorkItemTemplateModal(props: TSaveWorkItemTemplateModalProps) {
  const { isOpen, onClose, workspaceSlug, projectId, data, template, onSaved } = props;
  // plane hooks
  const { t } = useTranslation();
  // store hooks
  const { createTemplate, updateTemplate } = useWorkItemTemplate();
  // states
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    // a new template is named after the work item title, as a starting point
    setName(template?.name ?? data?.name?.trim() ?? "");
    setError(null);
  }, [isOpen, template, data]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    // the create dialog sits behind this one; keep its form from submitting too
    event.stopPropagation();
    if (!name.trim()) {
      setError(t("work_item_templates.save.name_required"));
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const payload = { name: name.trim(), ...(data ? { template_data: data } : {}) };
      const saved = template
        ? await updateTemplate(workspaceSlug, projectId, template.id, payload)
        : await createTemplate(workspaceSlug, projectId, payload);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: t(template ? "work_item_templates.save.updated" : "work_item_templates.save.success", {
          name: saved.name,
        }),
      });
      onSaved?.(saved);
      onClose();
    } catch (submitError) {
      const message = (submitError as { name?: string | string[] } | undefined)?.name;
      setError(
        typeof message === "string"
          ? message
          : Array.isArray(message)
            ? message.join(" ")
            : t("work_item_templates.save.error")
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <ModalCore isOpen={isOpen} handleClose={onClose} position={EModalPosition.CENTER} width={EModalWidth.LG}>
      <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-3 p-5">
        <h3 className="text-h5-medium text-primary">
          {!template
            ? t("work_item_templates.save.title")
            : data
              ? t("work_item_templates.select.update", { name: template.name })
              : t("work_item_templates.settings.rename")}
        </h3>
        {!template && <p className="text-body-xs-regular text-tertiary">{t("work_item_templates.save.description")}</p>}
        <InputGroup size="2xl">
          <Input
            size="2xl"
            type="text"
            name="template-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t("work_item_templates.save.name_placeholder")}
            maxLength={255}
            // oxlint-disable-next-line jsx-a11y/no-autofocus -- the name is the only thing to fill in
            autoFocus
          />
        </InputGroup>
        {error && <p className="text-caption-sm-regular text-danger-primary">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" size="sm" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" variant="primary" size="sm" loading={isSubmitting}>
            {isSubmitting ? t("work_item_templates.save.saving") : t("work_item_templates.save.save")}
          </Button>
        </div>
      </form>
    </ModalCore>
  );
}
