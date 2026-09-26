/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { MAX_FILE_SIZE, MAX_VIDEO_FILE_SIZE } from "@plane/constants";
// hooks
import { useInstance } from "@/hooks/store/use-instance";

type TReturnProps = {
  maxFileSize: number;
  maxVideoFileSize: number;
};

export const useFileSize = (): TReturnProps => {
  // store hooks
  const { config } = useInstance();

  return {
    maxFileSize: config?.file_size_limit ?? MAX_FILE_SIZE,
    maxVideoFileSize: config?.video_file_size_limit ?? MAX_VIDEO_FILE_SIZE,
  };
};
