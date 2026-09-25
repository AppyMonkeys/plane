/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { CloseOutline } from "@makeplane/propel/icons";
// ui
import { EModalPosition, EModalWidth, ModalCore } from "@plane/ui";

const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"]);
const VIDEO_EXTENSIONS = new Set(["mp4", "webm", "ogg", "ogv", "mov", "m4v"]);

export const isPreviewableAttachment = (fileExtension: string) => {
  const extension = fileExtension.toLowerCase();
  return IMAGE_EXTENSIONS.has(extension) || VIDEO_EXTENSIONS.has(extension);
};

type Props = {
  isOpen: boolean;
  onClose: () => void;
  fileURL: string;
  fileName: string;
  fileExtension: string;
};

export const AttachmentPreviewModal = (props: Props) => {
  const { isOpen, onClose, fileURL, fileName, fileExtension } = props;
  const extension = fileExtension.toLowerCase();
  const isVideo = VIDEO_EXTENSIONS.has(extension);
  const isImage = IMAGE_EXTENSIONS.has(extension);

  return (
    <ModalCore isOpen={isOpen} handleClose={onClose} position={EModalPosition.CENTER} width={EModalWidth.VIXL}>
      <div className="flex items-center justify-between gap-4 border-b border-subtle px-4 py-3">
        <p className="truncate text-14 font-medium text-primary">{fileName}</p>
        <button type="button" onClick={onClose} className="shrink-0 text-tertiary hover:text-primary">
          <CloseOutline className="size-4" />
        </button>
      </div>
      <div className="flex max-h-[80vh] items-center justify-center overflow-auto bg-canvas p-4">
        {isVideo && (
          // eslint-disable-next-line jsx-a11y/media-has-caption
          <video src={fileURL} controls autoPlay className="max-h-[75vh] max-w-full rounded-md" />
        )}
        {isImage && <img src={fileURL} alt={fileName} className="max-h-[75vh] max-w-full rounded-md object-contain" />}
      </div>
    </ModalCore>
  );
};
