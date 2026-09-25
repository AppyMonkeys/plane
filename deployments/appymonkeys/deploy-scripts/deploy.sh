#!/bin/sh
# Rolling deploy: pull the given branch, build each app image one at a
# time, run migrations, then recreate each running container one at a
# time -- pausing and checking free memory after every step, rather than
# building/starting everything at once. Run this ON the target host (e.g.
# EC2), from inside deployments/appymonkeys/.
#
# Building or starting several of these containers simultaneously has
# OOM-killed this stack before on a small box; going one at a time with a
# memory check in between is what actually keeps it stable.
#
# Usage:
#   ./deploy-scripts/deploy.sh [branch]
#
# Env overrides:
#   MIN_FREE_MB=150          pause longer if free memory drops below this
#   PAUSE_SECONDS=10         normal pause between steps
#   LOW_MEM_PAUSE_SECONDS=20 extra pause when below MIN_FREE_MB
set -eu

BRANCH="${1:-preview}"
MIN_FREE_MB=${MIN_FREE_MB:-150}
PAUSE_SECONDS=${PAUSE_SECONDS:-10}
LOW_MEM_PAUSE_SECONDS=${LOW_MEM_PAUSE_SECONDS:-20}

cd "$(dirname "$0")/.."
REPO_ROOT="$(cd ../.. && pwd)"

if command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD="docker-compose"
else
  COMPOSE_CMD="docker compose"
fi
COMPOSE="$COMPOSE_CMD -f docker-compose.yaml"

log() { echo "[deploy] $(date -Iseconds) $*"; }

free_mb() { awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo; }

wait_and_check() {
  # $1 = label for what was just started/built
  sleep "$PAUSE_SECONDS"
  mb=$(free_mb)
  log "after $1: ${mb}MB available"
  if [ "$mb" -lt "$MIN_FREE_MB" ]; then
    log "low memory (${mb}MB) after $1 -- pausing ${LOW_MEM_PAUSE_SECONDS}s before continuing"
    sleep "$LOW_MEM_PAUSE_SECONDS"
  fi
}

if [ -n "$(cd "$REPO_ROOT" && git status --porcelain)" ]; then
  log "ERROR: $REPO_ROOT has local changes -- commit, stash, or discard them first." >&2
  ( cd "$REPO_ROOT" && git status --short )
  exit 1
fi

log "pulling $BRANCH into $REPO_ROOT"
( cd "$REPO_ROOT" && git fetch origin "$BRANCH" && git checkout "$BRANCH" && git merge --ff-only "origin/$BRANCH" )
log "now at $(cd "$REPO_ROOT" && git log --oneline -1)"

# web/space/admin/live/api build from source; worker/beat-worker/migrator
# share api's image (plane-backend:local), so building api covers them too.
BUILD_SERVICES="web space admin live api"
for svc in $BUILD_SERVICES; do
  log "building $svc"
  $COMPOSE build "$svc"
  wait_and_check "building $svc"
done

log "running migrations"
$COMPOSE up -d migrator
sleep 10
$COMPOSE logs migrator --tail 30

# Dependency order: api before worker/beat-worker (share its image and
# depend on it being up), proxy last (fronts everything else).
RESTART_SERVICES="api worker beat-worker web admin space live proxy"
for svc in $RESTART_SERVICES; do
  log "starting $svc"
  $COMPOSE up -d "$svc"
  wait_and_check "starting $svc"
done

log "deploy complete. current status:"
$COMPOSE ps --format "table {{.Name}}\t{{.Status}}"
