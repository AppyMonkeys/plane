# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.conf import settings


def get_max_file_size(file_type: str) -> int:
    """Returns the max allowed upload size in bytes for the given mime type."""
    if file_type and file_type.startswith("video/"):
        return settings.VIDEO_FILE_SIZE_LIMIT
    return settings.FILE_SIZE_LIMIT
