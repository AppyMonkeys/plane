#!/usr/bin/env python3
"""
Attachments Plane's upload API refuses (over FILE_SIZE_LIMIT / VIDEO_FILE_SIZE_LIMIT),
done by hand in three steps:

  1. python3 manual_attachments.py prepare --jira-project LOK --plane-project LOKKO
     Downloads each missing attachment from Jira into .state/manual_attachments/,
     picks its storage key (Plane's own format: <workspace id>/<uuid hex>-<file name>),
     writes manifest.json and prints the `aws s3 cp` commands to run in CloudShell.

  2. (you) upload the files in CloudShell with those commands.

  3. python3 manual_attachments.py register --jira-project LOK --plane-project LOKKO
     Runs register_attachments_server.py in the api container: checks each object is
     in S3 with the right size, then creates the attachment records on the tickets.

Re-running prepare keeps the keys already in the manifest and skips finished downloads.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from build_plan import load_jira
from jira_api_to_plane import Jira, load_dotenv
from run_phase3 import API, HOST, KEY, REMOTE, SSH
from runlog import STATE_DIR, RunLog

WORKSPACE_ID = "d2d697c0-ba2e-44aa-8f10-9a6d46376917"  # lokko
BUCKET = "am-toolchain-plane"
KEY_PREFIX = "plane-uploads"  # AWS_S3_KEY_PREFIX on the server; the DB stores keys without it
FOLDER = STATE_DIR / "manual_attachments"
MANIFEST = FOLDER / "manifest.json"


def prepare(args, run: RunLog) -> int:
    plan = json.loads((STATE_DIR / f"plan_{args.jira_project}_to_{args.plane_project}.json").read_text())
    issues, _ = load_jira(args.jira_project)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    jira = Jira(
        os.environ.get("JIRA_BASE_URL", "https://appymonkeys.atlassian.net"),
        os.environ.get("JIRA_EMAIL", "kc@appymonkeys.com"),
        os.environ["JIRA_API_TOKEN"],
        min_interval=1.0,
    )
    for key, attachment_ids in plan["attachments_missing"].items():
        for attachment in issues[key]["fields"].get("attachment") or []:
            attachment_id = str(attachment["id"])
            if attachment_id not in attachment_ids:
                continue
            name = attachment["filename"]
            entry = manifest.setdefault(
                attachment_id,
                {
                    "jira_key": key,
                    "name": name,
                    "type": attachment.get("mimeType") or "application/octet-stream",
                    "size": int(attachment.get("size") or 0),
                    "asset_key": f"{WORKSPACE_ID}/{uuid.uuid4().hex}-{name}",
                },
            )
            local = FOLDER / key / name
            entry["local_file"] = str(local)
            local.parent.mkdir(parents=True, exist_ok=True)
            if local.exists() and local.stat().st_size == entry["size"]:
                run.ok(key, "already-downloaded", f"{name} ({entry['size'] / 1e6:.1f} MB)")
                continue
            try:
                got = jira.download(attachment["content"], local)
                if got != entry["size"]:
                    raise RuntimeError(f"downloaded {got} bytes, Jira reported {entry['size']}")
                run.ok(key, "downloaded", f"{name} ({got / 1e6:.1f} MB) -> {local}")
            except Exception as error:
                run.error(key, "download-failed", f"{name}: {error}")
    MANIFEST.write_text(json.dumps(manifest, indent=1))

    print("\n# --- CloudShell: upload these files (Actions -> Upload file), then run: ---")
    for attachment_id, entry in manifest.items():
        print(
            f"aws s3 cp '{Path(entry['local_file']).name}' "
            f"'s3://{BUCKET}/{KEY_PREFIX}/{entry['asset_key']}' --content-type '{entry['type']}'"
        )
    print("\n# check:")
    for entry in manifest.values():
        print(f"aws s3api head-object --bucket {BUCKET} --key '{KEY_PREFIX}/{entry['asset_key']}' --query ContentLength")
    return 0


def register(args, run: RunLog) -> int:
    subprocess.run(
        ["scp", "-q", "-o", "BatchMode=yes", "-i", KEY, str(Path(__file__).with_name("register_attachments_server.py")),
         str(MANIFEST), f"{HOST}:{REMOTE}/"],  # fmt: skip
        check=True,
    )
    subprocess.run([*SSH, f"docker cp ~/{REMOTE}/manifest.json {API}:/tmp/manifest.json"], check=True)
    result = subprocess.run(
        [*SSH, f"docker exec -i -e MANIFEST=/tmp/manifest.json -e PLANE_PROJECT={args.plane_project} {API} "
               f"python manage.py shell < ~/{REMOTE}/register_attachments_server.py"],  # fmt: skip
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4 and parts[0] == "OK":
            run.ok(*parts[1:])
        elif len(parts) == 4 and parts[0] == "ERR":
            run.error(*parts[1:])
    if result.returncode != 0:
        run.error("-", "server-script-failed", result.stderr[-1500:])
    return 1 if run.counts["error"] else 0


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["prepare", "register"])
    parser.add_argument("--jira-project", required=True)
    parser.add_argument("--plane-project", required=True)
    args = parser.parse_args()
    args.jira_project, args.plane_project = args.jira_project.upper(), args.plane_project.upper()
    run = RunLog(f"manual-attachments-{args.step}")
    code = prepare(args, run) if args.step == "prepare" else register(args, run)
    run.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
