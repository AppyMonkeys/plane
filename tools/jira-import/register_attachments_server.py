"""
Register attachments that were uploaded to S3 by hand (see manual_attachments.py).
Runs INSIDE the api container:

  docker exec -i -e MANIFEST=/tmp/manifest.json -e PLANE_PROJECT=LOKKO plane-app-api-1 \\
      python manage.py shell < register_attachments_server.py

For each manifest entry: the S3 object must exist with exactly the Jira size,
otherwise it is skipped. Then a FileAsset is created the way Plane's own upload
does (entity ISSUE_ATTACHMENT, is_uploaded, external_id = Jira attachment id) with
an "attachment created" activity row. No notifications. Safe to re-run: an
attachment already registered (same external id) is left alone.
"""

import json
import os

from django.db import transaction
from django.utils import timezone

from plane.db.models import FileAsset, Issue, IssueActivity, Project, User
from plane.settings.storage import S3Storage

MANIFEST = os.environ.get("MANIFEST", "/tmp/manifest.json")
PLANE_PROJECT = os.environ.get("PLANE_PROJECT", "LOKKO")
WORKSPACE = os.environ.get("WORKSPACE", "lokko")
ACTOR_EMAIL = os.environ.get("ACTOR_EMAIL", "varun.sharma@appymonkeys.com")
SOURCE = "jira_attachment_import"


def out(kind, key, action, detail=""):
    print(f"{kind}\t{key}\t{action}\t{str(detail).replace(chr(9), ' ')}", flush=True)


manifest = json.load(open(MANIFEST))
project = Project.objects.get(identifier__iexact=PLANE_PROJECT, workspace__slug=WORKSPACE)
actor = User.objects.get(email=ACTOR_EMAIL)
storage = S3Storage()

for attachment_id, entry in manifest.items():
    key = entry["jira_key"]
    issue = Issue.objects.filter(project=project, external_id=key).first()
    if not issue:
        out("ERR", key, "register-failed", "work item not found")
        continue
    if FileAsset.objects.filter(issue=issue, external_id=attachment_id, external_source=SOURCE).exists():
        out("OK", key, "already-registered", entry["name"])
        continue
    metadata = storage.get_object_metadata(object_name=entry["asset_key"])
    if not metadata or int(metadata.get("ContentLength") or 0) != entry["size"]:
        out("ERR", key, "not-in-s3", f"{entry['name']}: S3 has {metadata and metadata.get('ContentLength')}, need {entry['size']}")
        continue
    with transaction.atomic():
        asset = FileAsset.objects.create(
            attributes={"name": entry["name"], "type": entry["type"], "size": entry["size"]},
            asset=entry["asset_key"],
            size=entry["size"],
            workspace_id=project.workspace_id,
            project_id=project.id,
            issue=issue,
            created_by=actor,
            entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
            external_id=attachment_id,
            external_source=SOURCE,
            is_uploaded=True,
            storage_metadata=metadata,
        )
        IssueActivity.objects.create(
            issue=issue, project=project, workspace_id=project.workspace_id, actor=actor, verb="created",
            field="attachment", comment="created attachment", new_value="", new_identifier=asset.id,
            epoch=int(timezone.now().timestamp()),
        )  # fmt: skip
    out("OK", key, "attachment-registered", f"{entry['name']} ({entry['size'] / 1e6:.1f} MB) asset {asset.id}")
