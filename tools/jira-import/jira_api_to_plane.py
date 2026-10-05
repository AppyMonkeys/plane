#!/usr/bin/env python3
"""
Jira Cloud REST API -> Plane REST API (v1) ticket import.

API to API: reads tickets from Jira and creates work items in Plane through
Plane's public API (X-Api-Key). It never touches either database directly.

What it brings over, per ticket:
  - title, description (Jira-rendered HTML), original created date
  - Jira status -> Plane state, priority, labels -> Plane labels; issue type -> Plane work item type
    when the project has types switched on (a label otherwise)
  - people: the Jira reporter becomes the Plane creator and the Jira assignee
    the Plane assignee, when they have an account in the target project (see
    PEOPLE below; accounts are created with provision_plane_users.py). Anyone
    without one is kept as text in the description header
  - parent (sub-issue nesting), when the parent exists in the target project
  - comments, attributed to the Jira author when they have a Plane account
  - attachments (downloaded from Jira, uploaded via Plane's presigned upload)

Safe to re-run: every created work item/comment/attachment carries
external_source + external_id (the Jira key / comment id / attachment id).
Plane's API answers 409 for something that already exists, and a local state
file remembers what is finished, so a second run only does the remaining work.

Rate limits: both clients are throttled well under the server limits
(Plane: API_KEY_RATE_LIMIT, 60/min by default; Jira Cloud: burst based) and
back off on 429 using Retry-After. Nothing runs in parallel.

Credentials come from the environment (or the repo's gitignored .env):
  JIRA_API_TOKEN   Jira API token
  PLANE_API_KEY    Plane personal access token (Profile settings -> Tokens)
Optional: JIRA_BASE_URL, JIRA_EMAIL, PLANE_BASE_URL, PLANE_WORKSPACE_SLUG.

Examples:
  # first 10 tickets into the TEST project
  python3 jira_api_to_plane.py --jira-project LOK --since 2026-08-31 \\
      --plane-project TEST --limit 10

  # everything since 31 Aug into LOKKO
  python3 jira_api_to_plane.py --jira-project LOK --since 2026-08-31 \\
      --plane-project LOKKO
"""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import requests

# --- mapping (kept identical to the earlier CSV import, import_jira.py) -----

STATUS_TO_STATE = {
    "Done": "Done",
    "In Progress": "In Progress",
    "To Do": "Todo",
    "Reopened": "Todo",
    "Waived": "Waived",
    "On Hold": "On Hold",
    "In Review": "In Review",
    "Duplicate": "Duplicate",
}
FALLBACK_STATE = "Backlog"

# States Plane doesn't create by default: name -> (color, group)
EXTRA_STATES = {
    "On Hold": ("#A16207", "backlog"),
    "In Review": ("#0EA5E9", "started"),
    "Waived": ("#6B7280", "cancelled"),
    "Duplicate": ("#DC2626", "cancelled"),
}

PRIORITY_MAP = {"Highest": "urgent", "High": "high", "Medium": "medium", "Low": "low", "Lowest": "low"}

# Jira display name -> Plane account email (Jira Cloud hides most email
# addresses, so names are matched here). Accounts are created with
# provision_plane_users.py. Someone who isn't a member of the target Plane
# project is kept as text in the description instead.
PEOPLE = {
    "Varun Sharma": "varun.sharma@appymonkeys.com",
    "Pratik Sahoo": "pratik.sahoo@appymonkeys.com",
    "Kartikeya Chandrahas": "kc@appymonkeys.com",
    "Karthik Raghu": "karthik.raghu@appymonkeys.com",
    "Sonup Rimal": "sonup.rimal@appymonkeys.com",
    "Anurag Singh": "anurag.singh@appymonkeys.com",
    "Vidit Rawat": "vidit.rawat@appymonkeys.com",
    "Ansh": "ansh@appymonkeys.com",
    "Ranganath": "ranganath@appymonkeys.com",
    "Shourish Adhicary": "shourish@appymonkeys.com",
    "SAJI": "saji.j@appymonkeys.com",
    "Nithin Suresh": "nithin.suresh@appymonkeys.com",
    "Rohit": "rohit.chaoji@appymonkeys.com",
    "Shashwat Bhatt": "shashwat.bhatt@appymonkeys.com",
    "Saket Palla": "saket@appymonkeys.com",
    "Satish Kumar": "satish.kumar@appymonkeys.com",
    "A G": "angupte@gmail.com",
}

LABEL_COLOR = "#6B7280"
FALLBACK_MIME = "application/octet-stream"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_dotenv() -> None:
    """Read KEY=VALUE lines from the repo's .env without overriding real env vars."""
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"):
        if not candidate.is_file():
            continue
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# --- throttled HTTP clients --------------------------------------------------


class Throttled:
    """A requests session that spaces calls out and backs off on 429/5xx."""

    def __init__(self, name: str, min_interval: float, max_retries: int = 6):
        self.name = name
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.session = requests.Session()
        self._last = 0.0
        self.calls = 0

    def _wait(self) -> None:
        gap = self.min_interval - (time.monotonic() - self._last)
        if gap > 0:
            time.sleep(gap)

    def request(self, method: str, url: str, *, ok=(200, 201, 204), **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", 120)
        for attempt in range(1, self.max_retries + 1):
            self._wait()
            try:
                response = self.session.request(method, url, **kwargs)
            except requests.RequestException as error:
                self._last = time.monotonic()
                delay = min(60, 5 * attempt)
                log(f"  {self.name}: network error ({error.__class__.__name__}), retry in {delay}s")
                time.sleep(delay)
                continue
            self._last = time.monotonic()
            self.calls += 1

            if response.status_code == 429 or response.status_code >= 500:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else 15 * attempt
                delay = min(delay + 1, 120)
                log(f"  {self.name}: HTTP {response.status_code}, backing off {delay:.0f}s (attempt {attempt})")
                time.sleep(delay)
                continue

            # Jira reports how much burst budget is left; slow down before it runs out.
            remaining = response.headers.get("X-RateLimit-Remaining")
            if remaining is not None and remaining.isdigit() and int(remaining) < 20:
                time.sleep(2)

            if response.status_code not in ok:
                return response  # caller decides (e.g. 409 = already exists)
            return response
        raise RuntimeError(f"{self.name}: gave up on {method} {url} after {self.max_retries} attempts")


class Jira:
    def __init__(self, base_url: str, email: str, token: str, min_interval: float):
        self.base = base_url.rstrip("/")
        self.http = Throttled("jira", min_interval)
        self.http.session.auth = (email, token)
        self.http.session.headers["Accept"] = "application/json"

    def search(self, jql: str, limit: int | None):
        """Yield issues (with rendered HTML fields) matching the JQL, oldest first."""
        fields = [
            "summary", "description", "status", "priority", "issuetype", "labels", "assignee",
            "reporter", "created", "parent", "attachment", "comment",
        ]  # fmt: skip
        token, seen = None, 0
        while True:
            body = {"jql": jql, "maxResults": 50, "fields": fields, "expand": "renderedFields"}
            if token:
                body["nextPageToken"] = token
            response = self.http.request("POST", f"{self.base}/rest/api/3/search/jql", json=body)
            if response.status_code != 200:
                raise RuntimeError(f"Jira search failed: HTTP {response.status_code} {response.text[:300]}")
            data = response.json()
            for issue in data.get("issues", []):
                yield issue
                seen += 1
                if limit and seen >= limit:
                    return
            token = data.get("nextPageToken")
            if not token:
                return

    def comments(self, key: str):
        """All comments of an issue, with rendered HTML bodies."""
        out, start = [], 0
        while True:
            response = self.http.request(
                "GET",
                f"{self.base}/rest/api/3/issue/{key}/comment",
                params={"startAt": start, "maxResults": 100, "expand": "renderedBody", "orderBy": "created"},
            )
            if response.status_code != 200:
                raise RuntimeError(f"Jira comments failed for {key}: HTTP {response.status_code}")
            data = response.json()
            out += data.get("comments", [])
            start += len(data.get("comments", []))
            if start >= data.get("total", 0) or not data.get("comments"):
                return out

    def download(self, url: str, destination: Path) -> int:
        response = self.http.request("GET", url, stream=True, allow_redirects=True, timeout=600)
        if response.status_code != 200:
            raise RuntimeError(f"Jira download failed: HTTP {response.status_code}")
        size = 0
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                handle.write(chunk)
                size += len(chunk)
        return size


class Plane:
    def __init__(self, base_url: str, api_key: str, workspace: str, min_interval: float):
        self.base = f"{base_url.rstrip('/')}/api/v1/workspaces/{workspace}"
        self.http = Throttled("plane", min_interval)
        self.http.session.headers.update({"X-Api-Key": api_key, "Accept": "application/json"})

    def call(self, method: str, path: str, **kwargs) -> requests.Response:
        return self.http.request(method, f"{self.base}/{path.lstrip('/')}", **kwargs)

    def list_all(self, path: str, params: dict | None = None) -> list[dict]:
        """Follow Plane's cursor pagination and return every row."""
        rows, cursor = [], None
        while True:
            query = {"per_page": 100, **(params or {})}
            if cursor:
                query["cursor"] = cursor
            response = self.call("GET", path, params=query)
            if response.status_code != 200:
                raise RuntimeError(f"Plane GET {path} failed: HTTP {response.status_code} {response.text[:300]}")
            data = response.json()
            if isinstance(data, list):
                return data
            rows += data.get("results", [])
            if not data.get("next_page_results"):
                return rows
            cursor = data.get("next_cursor")


# --- streaming multipart body for the presigned S3 POST ----------------------


class MultipartFile:
    """File-like multipart/form-data body with a known length, so large
    attachments are streamed from disk instead of being held in memory
    (S3's POST upload needs Content-Length; it doesn't accept chunked)."""

    def __init__(self, fields: dict, file_path: Path, filename: str, content_type: str):
        self.boundary = f"----planeimport{int(time.time() * 1000)}"
        head = b""
        for name, value in fields.items():
            head += (
                f'--{self.boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
            ).encode()
        safe_name = filename.replace('"', "")
        head += (
            f'--{self.boundary}\r\nContent-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
        self._head = head
        self._tail = f"\r\n--{self.boundary}--\r\n".encode()
        self._file = file_path.open("rb")
        self._file_size = file_path.stat().st_size
        self._position = 0
        self.length = len(self._head) + self._file_size + len(self._tail)
        self.content_type = f"multipart/form-data; boundary={self.boundary}"

    def __len__(self) -> int:
        return self.length

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self.length - self._position
        out = b""
        while size > 0 and self._position < self.length:
            head_end = len(self._head)
            file_end = head_end + self._file_size
            if self._position < head_end:
                chunk = self._head[self._position : self._position + size]
            elif self._position < file_end:
                chunk = self._file.read(min(size, file_end - self._position))
            else:
                offset = self._position - file_end
                chunk = self._tail[offset : offset + size]
            if not chunk:
                break
            out += chunk
            self._position += len(chunk)
            size -= len(chunk)
        return out

    def close(self) -> None:
        self._file.close()


# --- the import --------------------------------------------------------------


class Importer:
    def __init__(self, args, jira: Jira, plane: Plane):
        self.args = args
        self.jira = jira
        self.plane = plane
        self.source = args.external_source
        self.attachment_source = args.attachment_external_source
        self.state_path = Path(args.state_dir) / f"{args.jira_project}_to_{args.plane_project}.json"
        self.state = {"issues": {}, "created_here": {}, "comments": {}, "attachments": {}, "parents_linked": {}}
        if self.state_path.is_file():
            self.state.update(json.loads(self.state_path.read_text()))
        self.stats = {k: 0 for k in ("created", "existing", "comments", "attachments", "parents", "failed")}
        self.failures: list[str] = []
        self.pending_parents: list[tuple[str, str]] = []  # (child key, parent key)

    def save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.state, indent=1))
        temp.replace(self.state_path)

    # -- target project metadata ---------------------------------------------

    def prepare(self) -> None:
        projects = self.plane.list_all("projects/")
        match = [p for p in projects if p.get("identifier", "").upper() == self.args.plane_project.upper()]
        if not match:
            raise SystemExit(f"Plane project {self.args.plane_project!r} not found in this workspace")
        self.project = match[0]
        self.pid = self.project["id"]
        log(f"Plane project: {self.project['identifier']} ({self.project['name']})")

        self.states = {s["name"]: s["id"] for s in self.plane.list_all(f"projects/{self.pid}/states/")}
        self.labels = {l["name"]: l["id"] for l in self.plane.list_all(f"projects/{self.pid}/labels/")}
        members = self.plane.list_all(f"projects/{self.pid}/members/")
        self.member_by_email = {(m.get("email") or "").lower(): m["id"] for m in members if m.get("email")}
        log(f"  {len(self.states)} states, {len(self.labels)} labels, {len(self.member_by_email)} project members")

        # Projects with work item types on get the Jira issue type as a real type instead of a label.
        self.types: dict[str, str] | None = None
        if self.project.get("is_issue_type_enabled"):
            response = self.plane.call("GET", f"projects/{self.pid}/work-item-types/")
            if response.status_code != 200:
                raise RuntimeError(f"could not list work item types: {response.status_code} {response.text[:200]}")
            self.types = {t["name"].lower(): t["id"] for t in response.json()}
            log(f"  work item types are on: {len(self.types)} types")

    def state_id(self, jira_status: str) -> str:
        name = STATUS_TO_STATE.get(jira_status, FALLBACK_STATE)
        if name not in self.states:
            color, group = EXTRA_STATES.get(name, ("#6B7280", "backlog"))
            if self.args.dry_run:
                log(f"  [dry-run] would create state {name!r}")
                self.states[name] = f"dry-run-{name}"
            else:
                response = self.plane.call(
                    "POST", f"projects/{self.pid}/states/", json={"name": name, "color": color, "group": group}
                )
                if response.status_code not in (200, 201):
                    raise RuntimeError(f"could not create state {name!r}: {response.status_code} {response.text[:200]}")
                self.states[name] = response.json()["id"]
                log(f"  created state {name!r}")
        return self.states[name]

    def type_id(self, fields: dict) -> str | None:
        """Plane work item type for the Jira issue type, or None when the project doesn't use types."""
        name = (fields.get("issuetype") or {}).get("name")
        if self.types is None or not name:
            return None
        if name.lower() not in self.types:
            if self.args.dry_run:
                log(f"  [dry-run] would create work item type {name!r}")
                self.types[name.lower()] = f"dry-run-{name}"
            else:
                response = self.plane.call("POST", f"projects/{self.pid}/work-item-types/", json={"name": name})
                if response.status_code not in (201, 409) or not response.json().get("id"):
                    raise RuntimeError(
                        f"could not create work item type {name!r}: {response.status_code} {response.text[:200]}"
                    )
                self.types[name.lower()] = response.json()["id"]
                log(f"  created work item type {name!r}")
        return self.types[name.lower()]

    def label_ids(self, names: list[str]) -> list[str]:
        ids = []
        for name in names:
            if name not in self.labels:
                if self.args.dry_run:
                    self.labels[name] = f"dry-run-{name}"
                else:
                    response = self.plane.call(
                        "POST", f"projects/{self.pid}/labels/", json={"name": name, "color": LABEL_COLOR}
                    )
                    if response.status_code in (200, 201):
                        self.labels[name] = response.json()["id"]
                        log(f"  created label {name!r}")
                    elif response.status_code == 409 and response.json().get("id"):
                        self.labels[name] = response.json()["id"]
                    else:
                        raise RuntimeError(f"could not create label {name!r}: {response.status_code} {response.text[:200]}")
            ids.append(self.labels[name])
        return ids

    # -- lookups ---------------------------------------------------------------

    def find_existing(self, jira_key: str) -> str | None:
        """Plane work item id for a Jira key: local state first, then the API."""
        if jira_key in self.state["issues"]:
            return self.state["issues"][jira_key]
        response = self.plane.call(
            "GET",
            f"projects/{self.pid}/work-items/",
            params={"external_id": jira_key, "external_source": self.source},
        )
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict) and data.get("id"):
                self.state["issues"][jira_key] = data["id"]
                return data["id"]
        return None

    # -- content ---------------------------------------------------------------

    def description(self, issue: dict) -> str:
        fields, rendered = issue["fields"], issue.get("renderedFields") or {}
        key = issue["key"]
        person = lambda p: (p or {}).get("displayName") or "Unassigned"  # noqa: E731
        parent = (fields.get("parent") or {}).get("key")
        rows = [f'Imported from Jira: <a href="{self.jira.base}/browse/{key}">{key}</a>']
        # People with a Plane account become the real creator/assignee; only
        # the ones we couldn't map are spelled out here so nothing is lost.
        if fields.get("reporter") and not self.user_id(fields.get("reporter")):
            rows.append(f"Reporter: {html.escape(person(fields.get('reporter')))}")
        if fields.get("assignee") and not self.user_id(fields.get("assignee")):
            rows.append(f"Assignee: {html.escape(person(fields.get('assignee')))}")
        if parent:
            rows.append(f"Jira parent: {parent}")
        body = rendered.get("description") or ""
        body = self.clean_html(body, fields.get("attachment") or [])
        return "<p>" + "<br>".join(rows) + "</p>" + (body or "<p></p>")

    @staticmethod
    def clean_html(body: str, attachments: list[dict]) -> str:
        """Jira's rendered HTML embeds images/videos by URLs that need a Jira
        login. The same files are uploaded as attachments, so replace each
        embed with a short pointer to the attachment instead of a broken image."""
        names = {str(a["id"]): a["filename"] for a in attachments}

        def embed(match: re.Match) -> str:
            tag = match.group(0)
            found = re.search(r"/attachment/(?:content|thumbnail)/(\d+)", tag)
            name = names.get(found.group(1)) if found else None
            if not name:
                alt = re.search(r'alt="([^"]*)"', tag)
                name = alt.group(1) if alt and alt.group(1) else "media"
            return f"<em>[attachment: {html.escape(name)}]</em>"

        body = re.sub(r"<img\b[^>]*>", embed, body, flags=re.I)
        body = re.sub(r"<(video|object|embed|iframe)\b.*?</\1>", "<em>[attachment: media]</em>", body, flags=re.I | re.S)
        body = re.sub(r"<span class=\"image-wrap\"[^>]*>(.*?)</span>", r"\1", body, flags=re.S)
        return body.strip()

    # -- one ticket ------------------------------------------------------------

    def import_issue(self, issue: dict) -> None:
        key, fields = issue["key"], issue["fields"]
        existing = self.find_existing(key) if key not in self.state["issues"] else self.state["issues"][key]

        if existing:
            issue_id = existing
            self.stats["existing"] += 1
            log(f"{key}: already in Plane, checking comments/attachments")
        else:
            payload = {
                "name": (fields.get("summary") or key)[:255],
                "description_html": self.description(issue),
                "state": self.state_id((fields.get("status") or {}).get("name", "")),
                "priority": PRIORITY_MAP.get((fields.get("priority") or {}).get("name", ""), "none"),
                "labels": self.label_ids(self.jira_labels(fields)),
                "external_id": key,
                "external_source": self.source,
                "created_at": fields.get("created"),
            }
            type_id = self.type_id(fields)
            if type_id:
                payload["type_id"] = type_id
            assignee = self.user_id(fields.get("assignee"))
            if assignee:
                payload["assignees"] = [assignee]
            reporter = self.user_id(fields.get("reporter"))
            if reporter:
                payload["created_by"] = reporter
            parent_key = (fields.get("parent") or {}).get("key")
            parent_id = self.find_existing(parent_key) if parent_key else None
            if parent_id:
                payload["parent"] = parent_id

            if self.args.dry_run:
                log(
                    f"{key}: [dry-run] would create {payload['name'][:50]!r} "
                    f"(state={STATUS_TO_STATE.get((fields.get('status') or {}).get('name', ''), FALLBACK_STATE)}, "
                    f"priority={payload['priority']}, attachments={len(fields.get('attachment') or [])}, "
                    f"comments={(fields.get('comment') or {}).get('total', 0)})"
                )
                return

            response = self.plane.call("POST", f"projects/{self.pid}/work-items/", json=payload)
            if response.status_code == 409 and response.json().get("id"):
                issue_id = response.json()["id"]
                self.stats["existing"] += 1
                log(f"{key}: already in Plane (409), checking comments/attachments")
            elif response.status_code in (200, 201):
                issue_id = response.json()["id"]
                self.stats["created"] += 1
                self.state["created_here"][key] = True
                log(f"{key}: created ({payload['name'][:60]})")
            else:
                raise RuntimeError(f"create failed: HTTP {response.status_code} {response.text[:300]}")
            self.state["issues"][key] = issue_id
            self.save_state()
            if parent_key and not parent_id:
                self.pending_parents.append((key, parent_key))

        if self.args.dry_run:
            return
        # A ticket this script didn't create came from the earlier CSV import,
        # whose comments carry no Jira id: compare text so they aren't repeated.
        preexisting = key not in self.state["created_here"]
        if not self.args.skip_comments:
            self.import_comments(key, issue_id, fields, preexisting)
        if not self.args.skip_attachments:
            self.import_attachments(key, issue_id, fields.get("attachment") or [])

    def jira_labels(self, fields: dict) -> list[str]:
        names = list(fields.get("labels") or [])
        # without work item types the issue type has no better home than a label
        issue_type = (fields.get("issuetype") or {}).get("name")
        if self.types is None and issue_type and issue_type not in names:
            names.append(issue_type)
        return names

    def user_id(self, person: dict | None) -> str | None:
        """Plane user id for a Jira person, if they are a member of the target project."""
        if not person:
            return None
        email = (person.get("emailAddress") or PEOPLE.get(person.get("displayName", ""), "")).lower()
        return self.member_by_email.get(email)

    @staticmethod
    def text_key(markup: str) -> str:
        """Comparable form of a comment: tags and whitespace removed, lower-cased."""
        text = html.unescape(re.sub(r"<[^>]+>", " ", markup or ""))
        return re.sub(r"\s+", "", text).lower()[:120]

    def import_comments(self, key: str, issue_id: str, fields: dict, preexisting: bool = False) -> None:
        summary = fields.get("comment") or {}
        if not summary.get("total"):
            return
        jira_comments = [c for c in self.jira.comments(key) if str(c["id"]) not in self.state["comments"]]
        if not jira_comments:
            return
        already_there = set()
        if preexisting:
            existing = self.plane.list_all(f"projects/{self.pid}/work-items/{issue_id}/comments/")
            already_there = {self.text_key(c.get("comment_html") or c.get("comment_stripped") or "") for c in existing}
            already_there.discard("")
        for comment in jira_comments:
            comment_id = str(comment["id"])
            # The earlier CSV import stored comments as "Author Name: text" with raw
            # Jira markup, so compare on the opening of the text, not the whole of it.
            opening = self.text_key(comment.get("renderedBody") or "")[:40]
            if opening and any(opening in existing_key for existing_key in already_there):
                self.state["comments"][comment_id] = True  # the earlier import already has it
                self.save_state()
                continue
            author = (comment.get("author") or {}).get("displayName", "Unknown")
            author_id = self.user_id(comment.get("author"))
            body = self.clean_html(comment.get("renderedBody") or "", fields.get("attachment") or []) or "<p></p>"
            if not author_id:
                # No Plane account: Plane would show the API key owner, so name the real author.
                body = f"<p><strong>{html.escape(author)}</strong> commented in Jira:</p>{body}"
            payload = {
                "comment_html": body,
                "external_id": comment_id,
                "external_source": self.source,
                "created_at": comment.get("created"),
            }
            if author_id:
                payload["created_by"] = author_id
            response = self.plane.call(
                "POST", f"projects/{self.pid}/work-items/{issue_id}/comments/", json=payload
            )
            if response.status_code in (200, 201):
                self.stats["comments"] += 1
            elif response.status_code != 409:
                raise RuntimeError(f"comment {comment_id} failed: HTTP {response.status_code} {response.text[:200]}")
            self.state["comments"][comment_id] = True
            self.save_state()

    def import_attachments(self, key: str, issue_id: str, attachments: list[dict]) -> None:
        for attachment in attachments:
            attachment_id = str(attachment["id"])
            if attachment_id in self.state["attachments"]:
                continue
            name, size = attachment["filename"], int(attachment.get("size") or 0)
            if self.args.max_file_mb and size > self.args.max_file_mb * 1024 * 1024:
                log(f"  {key}: skipping {name} ({size / 1e6:.1f} MB > --max-file-mb)")
                continue
            mime = attachment.get("mimeType") or mimetypes.guess_type(name)[0] or FALLBACK_MIME
            try:
                self.upload_attachment(key, issue_id, attachment_id, attachment["content"], name, mime, size)
                self.stats["attachments"] += 1
                self.state["attachments"][attachment_id] = True
                self.save_state()
            except Exception as error:  # keep going; the ticket itself is fine
                self.failures.append(f"{key} attachment {name}: {error}")
                log(f"  {key}: attachment {name} FAILED: {error}")

    def upload_attachment(self, key, issue_id, attachment_id, url, name, mime, size) -> None:
        base = f"projects/{self.pid}/work-items/{issue_id}/attachments/"
        # Ask Plane for the upload slot first: a 409 means this Jira attachment is
        # already on the ticket (this run or the earlier import), so nothing is
        # downloaded or uploaded twice.
        body = {
            "name": name,
            "type": mime,
            "size": size,
            "external_id": attachment_id,
            "external_source": self.attachment_source,
        }
        response = self.plane.call("POST", base, json=body)
        if response.status_code == 400 and "Invalid file type" in response.text and mime != FALLBACK_MIME:
            mime = body["type"] = FALLBACK_MIME
            response = self.plane.call("POST", base, json=body)
        if response.status_code == 409:
            self.stats["attachments"] -= 1  # counted by the caller; it was already there
            self.stats["attachments_existing"] = self.stats.get("attachments_existing", 0) + 1
            return
        if response.status_code != 200:
            raise RuntimeError(f"upload slot failed: HTTP {response.status_code} {response.text[:200]}")
        slot = response.json()
        granted = (slot.get("attachment") or {}).get("attributes", {}).get("size")
        if granted is not None and int(granted) < size:
            # Plane capped the size: the file is over FILE_SIZE_LIMIT / VIDEO_FILE_SIZE_LIMIT
            self.plane.call("DELETE", f"{base}{slot['asset_id']}/", ok=(200, 204))
            raise RuntimeError(f"{size / 1e6:.1f} MB is over Plane's upload limit ({int(granted) / 1e6:.0f} MB)")

        with tempfile.TemporaryDirectory(prefix="jira-import-") as folder:
            local = Path(folder) / "file"
            actual_size = self.jira.download(url, local)
            if actual_size != size:
                self.plane.call("DELETE", f"{base}{slot['asset_id']}/", ok=(200, 204))
                raise RuntimeError(f"downloaded {actual_size} bytes but Jira reported {size}")

            upload = slot["upload_data"]
            multipart = MultipartFile(upload["fields"], local, name, mime)
            try:
                # Straight to object storage (S3): not a Plane API call, so not throttled.
                stored = requests.post(
                    upload["url"],
                    data=multipart,
                    headers={"Content-Type": multipart.content_type, "Content-Length": str(len(multipart))},
                    timeout=1800,
                )
            finally:
                multipart.close()
            if stored.status_code not in (200, 201, 204):
                self.plane.call("DELETE", f"{base}{slot['asset_id']}/", ok=(200, 204))
                raise RuntimeError(f"storage upload failed: HTTP {stored.status_code} {stored.text[:200]}")

            confirm = self.plane.call("PATCH", f"{base}{slot['asset_id']}/", json={"is_uploaded": True})
            if confirm.status_code not in (200, 204):
                raise RuntimeError(f"confirm failed: HTTP {confirm.status_code} {confirm.text[:200]}")
            log(f"  {key}: attached {name} ({actual_size / 1e6:.1f} MB)")

    def link_pending_parents(self) -> None:
        """Second pass: children created before their parent existed in Plane."""
        for child_key, parent_key in self.pending_parents:
            if child_key in self.state["parents_linked"]:
                continue
            parent_id = self.find_existing(parent_key)
            if not parent_id:
                continue  # parent isn't in this project; it's recorded in the description
            response = self.plane.call(
                "PATCH",
                f"projects/{self.pid}/work-items/{self.state['issues'][child_key]}/",
                json={"parent": parent_id},
            )
            if response.status_code in (200, 201):
                self.stats["parents"] += 1
                self.state["parents_linked"][child_key] = parent_key
                self.save_state()

    # -- run -------------------------------------------------------------------

    def run(self) -> int:
        self.prepare()
        jql = f'project = {self.args.jira_project} AND created >= "{self.args.since}" ORDER BY created ASC'
        log(f"Jira query: {jql}" + (f" (first {self.args.limit})" if self.args.limit else ""))
        started = time.monotonic()
        count = 0
        for issue in self.jira.search(jql, self.args.limit):
            count += 1
            try:
                self.import_issue(issue)
            except Exception as error:
                self.stats["failed"] += 1
                self.failures.append(f"{issue['key']}: {error}")
                log(f"{issue['key']}: FAILED: {error}")
        if not self.args.dry_run:
            self.link_pending_parents()

        minutes = (time.monotonic() - started) / 60
        log(
            f"Done: {count} tickets in {minutes:.1f} min | created {self.stats['created']}, "
            f"already there {self.stats['existing']}, comments {self.stats['comments']}, "
            f"attachments {self.stats['attachments']} "
            f"(+{self.stats.get('attachments_existing', 0)} already there), "
            f"parents linked later {self.stats['parents']}, "
            f"failed {self.stats['failed']}"
        )
        log(f"API calls: Plane {self.plane.http.calls}, Jira {self.jira.http.calls}")
        if self.failures:
            log(f"{len(self.failures)} problem(s):")
            for failure in self.failures:
                log(f"  - {failure}")
        return 1 if self.failures else 0


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jira-project", required=True, help="Jira project key, e.g. LOK")
    parser.add_argument("--since", required=True, help="Import tickets created on/after this date (YYYY-MM-DD)")
    parser.add_argument("--plane-project", required=True, help="Plane project identifier, e.g. TEST or LOKKO")
    parser.add_argument("--limit", type=int, default=0, help="Only the first N tickets (oldest first)")
    parser.add_argument("--dry-run", action="store_true", help="Read from Jira and print what would be created")
    parser.add_argument("--skip-comments", action="store_true")
    parser.add_argument("--skip-attachments", action="store_true")
    parser.add_argument("--max-file-mb", type=int, default=0, help="Skip attachments larger than this (0 = no cap)")
    parser.add_argument(
        "--external-source",
        default="jira_csv_import",
        help="Tag stored on created items. Defaults to the earlier import's tag so tickets it "
        "already brought in are recognised as existing (no duplicates).",
    )
    parser.add_argument(
        "--attachment-external-source",
        default="jira_attachment_import",
        help="Tag stored on uploaded attachments (external_id = Jira attachment id). Defaults to "
        "the earlier attachment import's tag so files it already uploaded are not uploaded again.",
    )
    parser.add_argument(
        "--plane-rpm", type=float, default=45, help="Max Plane API requests per minute (server limit is 60)"
    )
    parser.add_argument("--jira-rps", type=float, default=2, help="Max Jira API requests per second")
    parser.add_argument("--state-dir", default=str(Path(__file__).resolve().parent / ".state"))
    args = parser.parse_args()

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.since):
        parser.error("--since must be YYYY-MM-DD")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", args.jira_project):
        parser.error("--jira-project must be a Jira project key")

    missing = [name for name in ("JIRA_API_TOKEN", "PLANE_API_KEY") if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Missing {', '.join(missing)} (set in the environment or the repo's .env)")

    jira = Jira(
        os.environ.get("JIRA_BASE_URL", "https://appymonkeys.atlassian.net"),
        os.environ.get("JIRA_EMAIL", "kc@appymonkeys.com"),
        os.environ["JIRA_API_TOKEN"],
        min_interval=1 / args.jira_rps,
    )
    plane = Plane(
        os.environ.get("PLANE_BASE_URL", "https://tickets.lokkobackend.com"),
        os.environ["PLANE_API_KEY"],
        os.environ.get("PLANE_WORKSPACE_SLUG", "lokko"),
        min_interval=60 / args.plane_rpm,
    )
    return Importer(args, jira, plane).run()


if __name__ == "__main__":
    sys.exit(main())
