---
name: deploy-plane
description: Use when deploying updated Plane code to a running host (e.g. EC2) -- rebuilds each service one at a time and restarts containers one at a time, monitoring memory between every step, instead of building/starting everything at once. Use when the user says "deploy", "redeploy", "push the update to EC2/prod", or similar.
user_invocable: true
---

# Deploy Plane (rolling, one container at a time)

Deploys the current `deployments/appymonkeys/deploy-scripts/deploy.sh` script to a
target host and runs it. The script itself does the actual build/restart
work one service at a time; this skill wraps it with the safety checks
that matter for a small/memory-constrained host: back up first, watch
memory as you go, verify health after.

**Building or restarting several of these containers at once has OOM-killed
this stack before.** Don't shortcut this by running
`docker compose up -d --build` for everything at once, even though it's
faster -- that's the exact failure mode this skill exists to avoid.

## Steps

1. **Confirm the target host and branch** with the user if not given
   (default branch: `preview`).

2. **Ask user to take a safety backup**, if the stack has one configured
   (`deployments/appymonkeys/backup-scripts/run-backup.sh` on a cron, or
   trigger one manually -- see `backup-scripts/README.md`). Wait for it
   to actually complete before proceeding; don't deploy on top of a stack
   with no recent recovery point.

3. **Make sure the source is actually pushed.** `deploy.sh` pulls from
   `origin/<branch>` -- if you've been making local changes, commit and
   push them first (the script will refuse to run over uncommitted local
   changes on the target host, but it won't pull work that was never
   pushed).

4. **SSH into the target host and run the script:**

   ```bash
   ssh -i <key> <user>@<host>
   cd ~/plane/deployments/appymonkeys
   ./deploy-scripts/deploy.sh <branch>
   ```

   Let it run to completion -- it already paces itself (build one
   service, pause, check memory; repeat for restarts). Don't run
   multiple `docker compose build`/`up` commands in parallel against the
   same host while this is in progress.

5. **If it reports low memory and pauses**, that's expected and handled
   automatically (it backs off `LOW_MEM_PAUSE_SECONDS` before
   continuing). Only intervene if a step outright fails.

6. **Verify health after it finishes:**

   ```bash
   curl -sS -o /dev/null -w "%{http_code}\n" https://<domain>/
   curl -sS -o /dev/null -w "%{http_code}\n" https://<domain>/api/instances/
   ```

   Check both the web app and the API respond `200`. If `edge-proxy` is
   involved and cert/domain config didn't change, it doesn't need
   touching -- `deploy.sh` doesn't restart it.

7. **Report what changed** (git log range deployed) and the final
   `docker compose ps` status back to the user.

## When NOT to use this

- Local dev machine, no memory constraints, want the fastest possible
  rebuild: just use `docker compose build && docker compose up -d
--build` directly.
- Changing `edge-proxy/` (TLS/domain config) or `docmost`'s config: those
  aren't covered by `deploy.sh` -- see
  `deployments/appymonkeys/edge-proxy/README.md`.
- First-ever deploy to a brand-new host: see the top-level
  `deployments/appymonkeys/README.md` quickstart instead (this skill
  assumes the stack is already running).
