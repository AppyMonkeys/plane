/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { Input, InputGroup } from "@makeplane/propel/components/input";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import type { TLogoProps, TWorkItemType } from "@plane/types";
import { cn } from "@plane/utils";
// local imports
import { DEFAULT_WORK_ITEM_TYPE_LOGO, WORK_ITEM_TYPE_COLORS, WORK_ITEM_TYPE_ICONS } from "../constants";
import { WorkItemTypeIcon } from "../icon";

type TWorkItemTypeFormProps = {
  data?: TWorkItemType;
  onSubmit: (data: Partial<TWorkItemType>) => Promise<void>;
  onClose: () => void;
};

export function WorkItemTypeForm(props: TWorkItemTypeFormProps) {
  const { data, onSubmit, onClose } = props;
  // plane hooks
  const { t } = useTranslation();
  // states
  const [name, setName] = useState(data?.name ?? "");
  const [description, setDescription] = useState(data?.description ?? "");
  const [logoProps, setLogoProps] = useState<TLogoProps>(
    data?.logo_props?.icon?.name ? data.logo_props : DEFAULT_WORK_ITEM_TYPE_LOGO
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const updateIcon = (icon: NonNullable<TLogoProps["icon"]>) =>
    setLogoProps((current) => ({ ...current, in_use: "icon", icon: { ...current.icon, ...icon } }));

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) {
      setError(t("work_item_types.settings.form.name_required"));
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      await onSubmit({ name: name.trim(), description: description.trim(), logo_props: logoProps });
      onClose();
    } catch (submitError) {
      const message = (submitError as { name?: string; error?: string } | undefined)?.name;
      setError(typeof message === "string" ? message : t("work_item_types.settings.form.save_error"));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={(event) => void handleSubmit(event)}
      className="flex flex-col gap-3 rounded-sm border border-subtle bg-surface-1 p-3.5"
    >
      <div className="flex items-start gap-3">
        <div className="mt-1.5">
          <WorkItemTypeIcon logoProps={logoProps} size={24} />
        </div>
        <div className="flex flex-grow flex-col gap-2">
          <InputGroup size="2xl">
            <Input
              size="2xl"
              type="text"
              name="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("work_item_types.settings.form.name_placeholder")}
              maxLength={100}
            />
          </InputGroup>
          <InputGroup size="2xl">
            <Input
              size="2xl"
              type="text"
              name="description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={t("work_item_types.settings.form.description_placeholder")}
              maxLength={255}
            />
          </InputGroup>
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-caption-sm-medium text-tertiary">{t("work_item_types.settings.form.icon")}</span>
        <div className="flex flex-wrap gap-1">
          {Object.entries(WORK_ITEM_TYPE_ICONS).map(([iconName, Icon]) => (
            <button
              key={iconName}
              type="button"
              aria-label={iconName}
              aria-pressed={logoProps.icon?.name === iconName}
              onClick={() => updateIcon({ name: iconName })}
              className={cn("grid size-7 place-items-center rounded-sm border text-secondary", {
                "border-accent-strong bg-layer-transparent-hover": logoProps.icon?.name === iconName,
                "border-transparent hover:bg-layer-transparent-hover": logoProps.icon?.name !== iconName,
              })}
            >
              <Icon className="size-4" />
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-caption-sm-medium text-tertiary">{t("work_item_types.settings.form.color")}</span>
        <div className="flex flex-wrap gap-1.5">
          {WORK_ITEM_TYPE_COLORS.map((color) => (
            <button
              key={color}
              type="button"
              aria-label={color}
              aria-pressed={logoProps.icon?.background_color === color}
              onClick={() => updateIcon({ background_color: color, color: "#ffffff" })}
              className={cn("size-6 rounded-sm border-2", {
                "border-strong ring-1 ring-accent-strong": logoProps.icon?.background_color === color,
                "border-transparent": logoProps.icon?.background_color !== color,
              })}
              style={{ backgroundColor: color }}
            />
          ))}
        </div>
      </div>

      {error && <p className="text-caption-sm-regular text-danger-primary">{error}</p>}

      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={onClose}>
          {t("common.cancel")}
        </Button>
        <Button type="submit" variant="primary" size="sm" loading={isSubmitting}>
          {data ? t("common.update") : t("common.create")}
        </Button>
      </div>
    </form>
  );
}
