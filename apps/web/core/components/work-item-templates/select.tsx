/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { usePopper } from "react-popper";
import { ChevronDownOutline, SearchOutline, TickOutline } from "@makeplane/propel/icons";
import { Combobox } from "@headlessui/react";
// plane imports
import { useTranslation } from "@plane/i18n";
import type { TWorkItemTemplate, TWorkItemTemplateData } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useWorkItemTemplate } from "@/hooks/store/use-work-item-template";
// local imports
import { SaveWorkItemTemplateModal } from "./save-modal";

const SAVE_AS_TEMPLATE = "save-as-template";
const UPDATE_TEMPLATE = "update-template";
const CLEAR_TEMPLATE = "clear-template";

type TOption = TWorkItemTemplate | typeof SAVE_AS_TEMPLATE | typeof UPDATE_TEMPLATE | typeof CLEAR_TEMPLATE;

type TWorkItemTemplateSelectProps = {
  workspaceSlug: string;
  projectId: string;
  /** The template currently filling the form. */
  value: string | null;
  onChange: (templateId: string | null) => void;
  /** The form's fields right now, for "Save as template". */
  getFormData: () => TWorkItemTemplateData;
  disabled?: boolean;
};

/**
 * "Template ▾" in the create dialog: pick a template to fill the form, or save what's in the form as one
 * -- like canned responses in Gmail.
 */
export const WorkItemTemplateSelect = observer(function WorkItemTemplateSelect(props: TWorkItemTemplateSelectProps) {
  const { workspaceSlug, projectId, value, onChange, getFormData, disabled = false } = props;
  // plane hooks
  const { t } = useTranslation();
  // store hooks
  const { getProjectTemplates, getTemplateById, fetchProjectTemplates } = useWorkItemTemplate();
  // states
  const [referenceElement, setReferenceElement] = useState<HTMLButtonElement | null>(null);
  const [popperElement, setPopperElement] = useState<HTMLDivElement | null>(null);
  const [query, setQuery] = useState("");
  const [saveModal, setSaveModal] = useState<{ data: TWorkItemTemplateData; template?: TWorkItemTemplate } | null>(
    null
  );
  // derived values
  const templates = getProjectTemplates(projectId);
  const selectedTemplate = getTemplateById(value);
  const matchingTemplates = templates.filter((template) =>
    template.name.toLowerCase().includes(query.trim().toLowerCase())
  );

  const { styles, attributes } = usePopper(referenceElement, popperElement, {
    placement: "bottom-start",
    modifiers: [{ name: "preventOverflow", options: { padding: 12 } }],
  });

  useEffect(() => {
    if (workspaceSlug && projectId) void fetchProjectTemplates(workspaceSlug, projectId).catch(() => undefined);
  }, [workspaceSlug, projectId, fetchProjectTemplates]);

  const handleSelect = (option: TOption | null) => {
    setQuery("");
    if (!option) return;
    if (option === SAVE_AS_TEMPLATE) setSaveModal({ data: getFormData() });
    else if (option === UPDATE_TEMPLATE && selectedTemplate)
      setSaveModal({ data: getFormData(), template: selectedTemplate });
    else if (option === CLEAR_TEMPLATE) onChange(null);
    else if (typeof option === "object") onChange(option.id);
  };

  const footerOptionClassName = ({ active }: { active: boolean }) =>
    cn("cursor-pointer truncate rounded-sm px-1 py-1.5 text-secondary select-none", {
      "bg-layer-1 text-primary": active,
    });

  return (
    <>
      <Combobox
        as="div"
        className="h-7 flex-shrink-0 text-left"
        value={null}
        onChange={handleSelect}
        disabled={disabled}
      >
        <Combobox.Button
          ref={setReferenceElement}
          type="button"
          className="flex h-full max-w-48 cursor-pointer items-center gap-1 rounded-sm border-[0.5px] border-strong px-2 py-0.5 text-caption-sm-regular hover:bg-layer-1"
        >
          <span className="truncate">{selectedTemplate?.name ?? t("work_item_templates.select.button")}</span>
          <ChevronDownOutline className="h-2.5 w-2.5 flex-shrink-0" />
        </Combobox.Button>

        <Combobox.Options modal={false} as="ul" className="fixed z-10">
          <div
            className="z-10 my-1 w-72 rounded-sm border border-strong bg-surface-1 py-2.5 text-11 shadow-raised-200 focus:outline-none"
            ref={setPopperElement}
            style={styles.popper}
            {...attributes.popper}
          >
            <div className="px-2">
              <div className="flex w-full items-center justify-start rounded-sm border border-subtle bg-surface-2 px-2">
                <SearchOutline className="h-3.5 w-3.5 flex-shrink-0 text-tertiary" />
                <Combobox.Input
                  className="w-full bg-transparent px-2 py-1 text-11 text-secondary placeholder:text-placeholder focus:outline-none"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={t("work_item_templates.select.search")}
                  displayValue={() => query}
                  onKeyDown={(event) => {
                    // first Escape clears the text, the next one closes the dropdown
                    if (query !== "" && event.key === "Escape") {
                      event.stopPropagation();
                      setQuery("");
                    }
                  }}
                  // oxlint-disable-next-line jsx-a11y/no-autofocus -- same as the other dropdowns: type straight away
                  autoFocus
                />
              </div>
            </div>
            <div className="vertical-scrollbar mt-2 scrollbar-sm max-h-56 overflow-y-scroll px-2 pr-0">
              {matchingTemplates.length > 0 ? (
                <ul className="space-y-1">
                  {matchingTemplates.map((template) => (
                    <Combobox.Option
                      as="li"
                      key={template.id}
                      value={template}
                      className={({ active }) =>
                        cn("flex cursor-pointer items-center gap-2 rounded-sm px-1 py-1.5 text-secondary select-none", {
                          "bg-layer-1 text-primary": active,
                        })
                      }
                    >
                      <span className="flex-grow truncate">{template.name}</span>
                      {template.id === value && <TickOutline className="h-3.5 w-3.5 flex-shrink-0" />}
                    </Combobox.Option>
                  ))}
                </ul>
              ) : (
                <p className="px-1 py-1.5 text-center text-tertiary">
                  {templates.length === 0
                    ? t("work_item_templates.select.empty")
                    : t("work_item_templates.select.no_match")}
                </p>
              )}
            </div>
            <div className="mt-2 space-y-1 border-t border-subtle px-2 pt-2">
              <Combobox.Option value={SAVE_AS_TEMPLATE} className={footerOptionClassName}>
                {t("work_item_templates.select.save_as")}
              </Combobox.Option>
              {selectedTemplate && (
                <>
                  <Combobox.Option value={UPDATE_TEMPLATE} className={footerOptionClassName}>
                    {t("work_item_templates.select.update", { name: selectedTemplate.name })}
                  </Combobox.Option>
                  <Combobox.Option value={CLEAR_TEMPLATE} className={footerOptionClassName}>
                    {t("work_item_templates.select.clear")}
                  </Combobox.Option>
                </>
              )}
            </div>
          </div>
        </Combobox.Options>
      </Combobox>
      <SaveWorkItemTemplateModal
        isOpen={!!saveModal}
        onClose={() => setSaveModal(null)}
        workspaceSlug={workspaceSlug}
        projectId={projectId}
        data={saveModal?.data}
        template={saveModal?.template}
        onSaved={(template) => onChange(template.id)}
      />
    </>
  );
});
