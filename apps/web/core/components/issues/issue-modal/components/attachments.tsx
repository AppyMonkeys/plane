/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { useDropzone } from "react-dropzone";
import { FileText, Film, Paperclip, X } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { cn } from "@plane/utils";
// hooks
import { useIssueModal } from "@/hooks/context/use-issue-modal";
import { useFileSize } from "@/hooks/use-file-size";

const formatSize = (bytes: number) =>
  bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;

const fileKey = (file: File) => `${file.name}-${file.size}-${file.lastModified}`;

/**
 * Adds files to the work item being created, skipping ones over the upload limit (a toast names
 * them) and ones already in the list. Shared by the attach button, drag and drop, and paste.
 */
export const useAddPendingAttachments = () => {
  const { t } = useTranslation();
  const { setPendingAttachments } = useIssueModal();
  const { maxFileSize, maxVideoFileSize } = useFileSize();

  return (files: File[]) => {
    const tooLarge: string[] = [];
    const accepted = files.filter((file) => {
      const limit = file.type.startsWith("video/") ? maxVideoFileSize : maxFileSize;
      if (file.size <= limit) return true;
      tooLarge.push(`${file.name} (${t("issue.attachments.max_size", { size: Math.round(limit / 1024 / 1024) })})`);
      return false;
    });

    if (tooLarge.length > 0)
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t("issue.attachments.too_large_title"),
        message: tooLarge.join(", "),
      });

    if (accepted.length > 0)
      setPendingAttachments((current) => {
        const known = new Set(current.map(fileKey));
        return [...current, ...accepted.filter((file) => !known.has(fileKey(file)))];
      });
  };
};

type TPendingAttachmentChipProps = {
  file: File;
  onRemove: () => void;
};

function PendingAttachmentChip(props: TPendingAttachmentChipProps) {
  const { file, onRemove } = props;
  const { t } = useTranslation();
  const isImage = file.type.startsWith("image/");
  // thumbnail for images; the object URL is released again when the chip goes away
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!isImage) return;
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file, isImage]);

  return (
    <div className="flex max-w-56 items-center gap-2 rounded-sm border-[0.5px] border-strong bg-layer-1 py-1 pr-1 pl-1.5">
      {previewUrl ? (
        <img src={previewUrl} alt="" className="size-7 flex-shrink-0 rounded-xs object-cover" />
      ) : (
        <span className="grid size-7 flex-shrink-0 place-items-center rounded-xs bg-layer-2 text-tertiary">
          {file.type.startsWith("video/") ? <Film className="size-4" /> : <FileText className="size-4" />}
        </span>
      )}
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-caption-sm-medium text-primary">{file.name}</span>
        <span className="text-caption-xs-regular text-tertiary">{formatSize(file.size)}</span>
      </div>
      <button
        type="button"
        onClick={onRemove}
        aria-label={t("issue.attachments.remove", { name: file.name })}
        className="grid size-5 flex-shrink-0 place-items-center rounded-xs text-tertiary hover:bg-layer-transparent-hover hover:text-primary"
      >
        <X className="size-3.5" />
      </button>
    </div>
  );
}

/**
 * The attach row of the create dialog. Files picked here are kept in the browser and uploaded as
 * attachments once the work item exists (see CreateUpdateIssueModalBase).
 */
export const IssueModalAttachments = observer(function IssueModalAttachments() {
  // plane hooks
  const { t } = useTranslation();
  // context
  const { pendingAttachments, setPendingAttachments } = useIssueModal();
  const addPendingAttachments = useAddPendingAttachments();

  const { getRootProps, getInputProps, open, isDragActive } = useDropzone({
    onDrop: (acceptedFiles) => addPendingAttachments(acceptedFiles),
    noClick: true,
    noKeyboard: true,
    multiple: true,
  });

  return (
    <div
      {...getRootProps()}
      className={cn("mt-2 flex flex-wrap items-center gap-2 rounded-sm border border-dashed border-transparent py-1", {
        "border-accent-strong bg-accent-primary/5": isDragActive,
      })}
    >
      <input {...getInputProps()} />
      <button
        type="button"
        onClick={open}
        className="flex h-7 items-center gap-1.5 rounded-sm border-[0.5px] border-strong px-2 text-caption-sm-regular text-secondary hover:bg-layer-transparent-hover"
      >
        <Paperclip className="size-3.5 flex-shrink-0" />
        {t("issue.attachments.attach")}
      </button>
      {pendingAttachments.length === 0 && (
        <span className="text-caption-sm-regular text-placeholder">{t("issue.attachments.hint")}</span>
      )}
      {pendingAttachments.map((file) => (
        <PendingAttachmentChip
          key={fileKey(file)}
          file={file}
          onRemove={() => setPendingAttachments((current) => current.filter((item) => item !== file))}
        />
      ))}
    </div>
  );
});
