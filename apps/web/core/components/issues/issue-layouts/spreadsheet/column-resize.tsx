/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useRef } from "react";
import type { CSSProperties, KeyboardEvent, PointerEvent } from "react";

// Column widths of the spreadsheet (table) layout, chosen by dragging the edge of a column header.
//
// A width lives in a CSS variable on the <table>, and every cell of the column sizes itself from it.
// Dragging therefore only writes one style property -- no row re-renders, however long the list is.
// Widths are remembered per browser and apply to every table layout.

const STORAGE_KEY = "plane:spreadsheet-column-widths";

/** Key of the first column (identifier + title), which is not a display property. */
export const NAME_COLUMN_KEY = "name";

const MIN_WIDTH = 96;
const MIN_NAME_WIDTH = 380;
const MAX_WIDTH = 1200;
const KEYBOARD_STEP = 16;

const widthVariable = (columnKey: string) => `--spreadsheet-column-${columnKey}`;

const clampWidth = (columnKey: string, width: number) =>
  Math.round(Math.min(Math.max(width, columnKey === NAME_COLUMN_KEY ? MIN_NAME_WIDTH : MIN_WIDTH), MAX_WIDTH));

const readStoredWidths = (): Record<string, number> => {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    if (!stored || typeof stored !== "object") return {};
    return Object.fromEntries(
      Object.entries(stored).filter((entry): entry is [string, number] => typeof entry[1] === "number")
    );
  } catch {
    return {};
  }
};

const storeWidth = (columnKey: string, width: number | null) => {
  try {
    const widths = readStoredWidths();
    if (width === null) delete widths[columnKey];
    else widths[columnKey] = width;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(widths));
  } catch {
    /* storage unavailable (private mode etc.) -- the width just lasts until the page reloads */
  }
};

/**
 * Sizing for a cell of the given column: the chosen width when there is one, otherwise the
 * column's natural sizing (`defaultMinWidth` / `defaultMaxWidth`).
 */
export const getColumnWidthStyle = (
  columnKey: string,
  defaultMinWidth: string,
  defaultMaxWidth: string = "none"
): CSSProperties => ({
  width: `var(${widthVariable(columnKey)}, auto)`,
  minWidth: `var(${widthVariable(columnKey)}, ${defaultMinWidth})`,
  maxWidth: `var(${widthVariable(columnKey)}, ${defaultMaxWidth})`,
});

/** Puts the remembered widths on a table. Call once when the table mounts. */
export const applyStoredColumnWidths = (table: HTMLTableElement | null) => {
  if (!table) return;
  Object.entries(readStoredWidths()).forEach(([columnKey, width]) => {
    table.style.setProperty(widthVariable(columnKey), `${clampWidth(columnKey, width)}px`);
  });
};

const currentWidth = (element: HTMLElement) => element.closest("th")?.getBoundingClientRect().width ?? 0;

type TColumnResizeHandleProps = {
  columnKey: string;
};

/**
 * The draggable right edge of a column header. Drag to resize, double-click to go back to the
 * automatic width; with the keyboard, focus it and use the left/right arrows.
 * Must be rendered inside a positioned <th>.
 */
export function ColumnResizeHandle(props: TColumnResizeHandleProps) {
  const { columnKey } = props;
  // drag state
  const drag = useRef<{ startX: number; startWidth: number; width: number } | null>(null);

  const setWidth = (element: HTMLElement, width: number) => {
    const clamped = clampWidth(columnKey, width);
    element.closest("table")?.style.setProperty(widthVariable(columnKey), `${clamped}px`);
    return clamped;
  };

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const startWidth = currentWidth(event.currentTarget);
    drag.current = { startX: event.clientX, startWidth, width: startWidth };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    drag.current.width = setWidth(event.currentTarget, drag.current.startWidth + event.clientX - drag.current.startX);
  };

  const handlePointerUp = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
    // a plain click (no movement) leaves the column as it was
    if (drag.current.width !== drag.current.startWidth) storeWidth(columnKey, drag.current.width);
    drag.current = null;
  };

  const handleReset = (element: HTMLElement) => {
    element.closest("table")?.style.removeProperty(widthVariable(columnKey));
    storeWidth(columnKey, null);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight" && event.key !== "Enter") return;
    // keep the table's own arrow-key cell navigation out of it
    event.preventDefault();
    event.stopPropagation();
    if (event.key === "Enter") {
      handleReset(event.currentTarget);
      return;
    }
    const step = event.key === "ArrowRight" ? KEYBOARD_STEP : -KEYBOARD_STEP;
    storeWidth(columnKey, setWidth(event.currentTarget, currentWidth(event.currentTarget) + step));
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize column"
      aria-valuemin={columnKey === NAME_COLUMN_KEY ? MIN_NAME_WIDTH : MIN_WIDTH}
      aria-valuemax={MAX_WIDTH}
      title="Drag to resize · double-click to reset"
      tabIndex={0}
      className="absolute top-0 -right-px z-[1] h-full w-1.5 cursor-col-resize touch-none bg-transparent select-none hover:bg-accent-primary/40 focus-visible:bg-accent-primary/40 focus-visible:outline-none active:bg-accent-primary"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      onDoubleClick={(event) => {
        event.stopPropagation();
        handleReset(event.currentTarget);
      }}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={handleKeyDown}
    />
  );
}
