/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { Check, ChevronDown } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { CustomMenu } from "@plane/ui";
import { cn } from "@plane/utils";
// hooks
import { useWorkItemType } from "@/hooks/store/use-work-item-type";
// local imports
import { WorkItemTypeIcon } from "./icon";

type TWorkItemTypeDropdownProps = {
  projectId: string;
  value: string | null | undefined;
  onChange: (typeId: string) => void;
  disabled?: boolean;
  /** "icon" shows just the type icon (next to a work item key), "button" shows icon and name */
  variant?: "icon" | "button";
  iconSize?: number;
  buttonClassName?: string;
  tabIndex?: number;
};

export const WorkItemTypeDropdown = observer(function WorkItemTypeDropdown(props: TWorkItemTypeDropdownProps) {
  const {
    projectId,
    value,
    onChange,
    disabled = false,
    variant = "button",
    iconSize = 16,
    buttonClassName,
    tabIndex,
  } = props;
  // plane hooks
  const { t } = useTranslation();
  // store hooks
  const { getWorkItemTypeById, getProjectWorkItemTypes } = useWorkItemType();
  // derived values
  const selectedType = getWorkItemTypeById(value);
  // a disabled type stays visible on the work items that already have it, but can't be picked again
  const options = getProjectWorkItemTypes(projectId).filter((type) => type.is_active || type.id === value);

  const button =
    variant === "icon" ? (
      <span
        className={cn(
          "flex items-center gap-0.5 rounded-sm p-0.5",
          { "hover:bg-layer-transparent-hover": !disabled },
          buttonClassName
        )}
      >
        <WorkItemTypeIcon logoProps={selectedType?.logo_props} size={iconSize} />
        {!disabled && <ChevronDown className="size-3 text-tertiary" />}
      </span>
    ) : (
      <span
        className={cn(
          "flex h-full items-center gap-1.5 rounded-sm border-[0.5px] border-strong px-2 py-0.5 text-caption-sm-regular text-secondary",
          { "hover:bg-layer-transparent-hover": !disabled },
          buttonClassName
        )}
      >
        {selectedType ? (
          <>
            <WorkItemTypeIcon logoProps={selectedType.logo_props} size={iconSize} />
            <span className="max-w-32 truncate">{selectedType.name}</span>
          </>
        ) : (
          <span className="text-placeholder">{t("work_item_types.singular")}</span>
        )}
        {!disabled && <ChevronDown className="size-3 flex-shrink-0" />}
      </span>
    );

  return (
    <CustomMenu
      customButton={button}
      customButtonTabIndex={tabIndex}
      disabled={disabled}
      placement="bottom-start"
      maxHeight="lg"
      closeOnSelect
      ariaLabel={
        selectedType ? `${t("work_item_types.singular")}: ${selectedType.name}` : t("work_item_types.singular")
      }
    >
      {options.map((type) => (
        <CustomMenu.MenuItem key={type.id} onClick={() => type.id !== value && onChange(type.id)}>
          <div className="flex min-w-36 items-center gap-2">
            <WorkItemTypeIcon logoProps={type.logo_props} size={16} />
            <span className="flex-grow truncate">{type.name}</span>
            {type.id === value && <Check className="size-3.5 flex-shrink-0" />}
          </div>
        </CustomMenu.MenuItem>
      ))}
    </CustomMenu>
  );
});
