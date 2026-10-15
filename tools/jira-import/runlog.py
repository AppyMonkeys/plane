"""
Two log files per run, shared by the Jira -> Plane sync scripts:

  .state/runs/<timestamp>-<script>/success.log   one line per thing done
  .state/runs/<timestamp>-<script>/errors.log    one line per failure / skip, with the reason

Lines are tab-separated: time, ticket (or "-"), action, detail. Everything is
also echoed to stdout so a run can be followed live.
"""

from __future__ import annotations

import time
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent / ".state"


class RunLog:
    def __init__(self, script: str):
        self.dir = STATE_DIR / "runs" / f"{time.strftime('%Y%m%d-%H%M%S')}-{script}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._success = (self.dir / "success.log").open("a", buffering=1)
        self._errors = (self.dir / "errors.log").open("a", buffering=1)
        self.counts = {"ok": 0, "error": 0}
        self.info(f"logs in {self.dir}")

    @staticmethod
    def _line(ticket: str, action: str, detail: str) -> str:
        detail = str(detail).replace("\n", " ").replace("\t", " ")
        return f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{ticket or '-'}\t{action}\t{detail}"

    def ok(self, ticket: str, action: str, detail: str = "") -> None:
        line = self._line(ticket, action, detail)
        self._success.write(line + "\n")
        self.counts["ok"] += 1
        print(line, flush=True)

    def error(self, ticket: str, action: str, detail: str = "") -> None:
        line = self._line(ticket, action, detail)
        self._errors.write(line + "\n")
        self.counts["error"] += 1
        print("ERROR " + line, flush=True)

    @staticmethod
    def info(msg: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    def close(self) -> None:
        self.info(f"success lines: {self.counts['ok']}, error lines: {self.counts['error']} ({self.dir})")
        self._success.close()
        self._errors.close()
