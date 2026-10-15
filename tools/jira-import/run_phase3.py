#!/usr/bin/env python3
"""
Phase 3 runner: uploads phase3_server.py + the plan to the host and runs it in
the api container. Dry run (rolled back) by default.

  python3 run_phase3.py --jira-project LOK --plane-project LOKKO            # dry run
  python3 run_phase3.py --jira-project LOK --plane-project LOKKO --commit   # for real

--commit first takes a pg_dump of the whole database on the host
(~/jira-sync/backup-before-phase3-<time>.dump) and stops if that fails.
The server's OK/ERR lines go to success.log / errors.log (runlog.py).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from runlog import STATE_DIR, RunLog

HERE = Path(__file__).resolve().parent
KEY = str(Path.home() / ".ssh/am-us-west-2.pem")
HOST = "ec2-user@ec2-54-149-251-138.us-west-2.compute.amazonaws.com"
API, DB = "plane-app-api-1", "plane-app-plane-db-1"
REMOTE = "jira-sync"
SSH = ["ssh", "-o", "ConnectTimeout=15", "-o", "BatchMode=yes", "-i", KEY, HOST]


def remote(command: str, run: RunLog, timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run([*SSH, command], capture_output=True, text=True, timeout=timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jira-project", required=True)
    parser.add_argument("--plane-project", required=True)
    parser.add_argument("--commit", action="store_true", help="Commit (default: dry run, rolled back)")
    args = parser.parse_args()
    plan = STATE_DIR / f"plan_{args.jira_project.upper()}_to_{args.plane_project.upper()}.json"
    run = RunLog(f"phase3-{args.jira_project.upper()}" + ("-COMMIT" if args.commit else "-dry"))

    subprocess.run([*SSH, f"mkdir -p ~/{REMOTE}"], check=True)
    subprocess.run(
        ["scp", "-q", "-o", "BatchMode=yes", "-i", KEY, str(HERE / "phase3_server.py"), str(plan),
         f"{HOST}:{REMOTE}/"],  # fmt: skip
        check=True,
    )
    subprocess.run([*SSH, f"docker cp ~/{REMOTE}/{plan.name} {API}:/tmp/plan.json"], check=True)

    if args.commit:
        # Streamed over SSH straight to this machine; nothing is left on the host.
        backup = STATE_DIR / "backups" / f"plane-before-phase3-{time.strftime('%Y%m%d-%H%M%S')}.dump"
        backup.parent.mkdir(parents=True, exist_ok=True)
        run.info(f"backing up the database over ssh to {backup}")
        dump = "PGPASSWORD=\"$POSTGRES_PASSWORD\" pg_dump -U \"$POSTGRES_USER\" -Fc \"$POSTGRES_DB\""
        with backup.open("wb") as handle:
            result = subprocess.run([*SSH, f"docker exec {DB} sh -c '{dump}'"], stdout=handle, stderr=subprocess.PIPE, timeout=1800)
        if result.returncode != 0 or backup.stat().st_size < 1024 or backup.read_bytes()[:5] != b"PGDMP":
            run.error("-", "backup-failed", result.stderr.decode()[-500:])
            run.close()
            return 1
        # integrity: the server's pg_restore must be able to read the whole table of contents
        with backup.open("rb") as handle:
            check = subprocess.run(
                [*SSH, f"docker exec -i {DB} pg_restore --list"], stdin=handle, capture_output=True, timeout=600
            )
        entries = sum(1 for line in check.stdout.decode().splitlines() if line and not line.startswith(";"))
        if check.returncode != 0 or entries == 0:
            run.error("-", "backup-unreadable", check.stderr.decode()[-500:])
            run.close()
            return 1
        run.ok("-", "backup", f"{backup} {backup.stat().st_size / 1e6:.1f} MB, {entries} entries")

    run.info("running phase 3 in the api container" + (" (COMMIT)" if args.commit else " (dry run, rolled back)"))
    result = remote(
        f"docker exec -i -e PLAN=/tmp/plan.json -e DRY_RUN={'0' if args.commit else '1'} {API} "
        f"python manage.py shell < ~/{REMOTE}/phase3_server.py",
        run,
    )
    (run.dir / "server-output.txt").write_text(result.stdout + "\n--- stderr ---\n" + result.stderr)
    outcome = None
    for line in result.stdout.splitlines():
        parts = line.split("\t", 3)
        if parts[0] == "OK" and len(parts) == 4:
            run._success.write("\t".join([time.strftime("%Y-%m-%d %H:%M:%S"), *parts[1:]]) + "\n")
            run.counts["ok"] += 1
        elif parts[0] == "ERR" and len(parts) == 4:
            run.error(parts[1], parts[2], parts[3])
        elif parts[0] == "PHASE3_RESULT":
            outcome = line
    if result.returncode != 0 or not outcome:
        run.error("-", "server-script-failed", (result.stderr or result.stdout)[-1500:])
    run.info(outcome or "no PHASE3_RESULT line: the transaction was rolled back (see server-output.txt)")
    subprocess.run([*SSH, f"docker exec {API} rm -f /tmp/plan.json"])
    run.close()
    expected = "COMMITTED" if args.commit else "DRY_RUN_ROLLED_BACK"
    return 0 if outcome and f"\t{expected}\t" in outcome else 1


if __name__ == "__main__":
    sys.exit(main())
