/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { usePopper } from "react-popper";
import { ChevronDownOutline } from "@makeplane/propel/icons";
import { Popover } from "@headlessui/react";
// plane imports
import { cn } from "@plane/utils";

type TFilterBarDropdownProps = {
  /** What the button says, e.g. "Status" or "Status: Done +1". */
  label: React.ReactNode;
  isActive?: boolean;
  /** The panel; gets a function that closes it. */
  children: (close: () => void) => React.ReactNode;
  panelClassName?: string;
  buttonClassName?: string;
  hideChevron?: boolean;
  onOpen?: () => void;
};

/** A button of the filter bar that opens a panel under it, like Jira's basic search fields. */
export function FilterBarDropdown(props: TFilterBarDropdownProps) {
  const { label, isActive = false, children, panelClassName, buttonClassName, hideChevron = false, onOpen } = props;
  const [referenceElement, setReferenceElement] = useState<HTMLButtonElement | null>(null);
  const [popperElement, setPopperElement] = useState<HTMLElement | null>(null);
  const { styles, attributes } = usePopper(referenceElement, popperElement, {
    placement: "bottom-start",
    strategy: "fixed",
    modifiers: [{ name: "preventOverflow", options: { padding: 12 } }],
  });

  return (
    <Popover className="relative flex-shrink-0">
      {({ close }) => (
        <>
          <Popover.Button
            ref={setReferenceElement}
            onClick={onOpen}
            className={cn(
              "flex h-7 max-w-64 items-center gap-1 rounded-sm border-[0.5px] px-2 text-caption-md-regular whitespace-nowrap outline-none",
              isActive
                ? "border-accent-strong bg-accent-subtle text-accent-primary"
                : "border-strong text-secondary hover:bg-layer-1",
              buttonClassName
            )}
          >
            <span className="truncate">{label}</span>
            {!hideChevron && <ChevronDownOutline className="h-3 w-3 flex-shrink-0" />}
          </Popover.Button>
          <Popover.Panel
            ref={setPopperElement}
            style={styles.popper}
            {...attributes.popper}
            className={cn(
              "z-20 my-1 w-64 rounded-sm border border-strong bg-surface-1 py-2 text-caption-md-regular shadow-raised-200",
              panelClassName
            )}
          >
            {children(close)}
          </Popover.Panel>
        </>
      )}
    </Popover>
  );
}
