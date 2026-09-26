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
#   SWAP_SIZE_MB=4096        swapfile to create if the host has no swap
#   BUILD_MIN_MB=3500        refuse to start a build below this much
#                            available memory + free swap
#   TURBO_CONCURRENCY=1      frontend build knobs passed as build args
#   NODE_MAX_OLD_SPACE_SIZE=1536
#   BUILD_THREADS=1
#   MIN_DISK_FREE_MB=6000    refuse to start building below this much free
#                            disk (a full frontend build needs several GB)
#
# A single frontend image build peaks at ~3.4GB even with the knobs above
# (~5GB without them), more than a 4GB host has free with the stack running.
# The builds run inside dockerd, so the checks between steps can't stop a
# spike mid-build -- without swap the host freezes (even sshd) instead of
# slowing down. Hence the swapfile and the pre-build memory gate.
set -eu

BRANCH="${1:-preview}"
MIN_FREE_MB=${MIN_FREE_MB:-150}
PAUSE_SECONDS=${PAUSE_SECONDS:-10}
LOW_MEM_PAUSE_SECONDS=${LOW_MEM_PAUSE_SECONDS:-20}
SWAP_SIZE_MB=${SWAP_SIZE_MB:-4096}
BUILD_MIN_MB=${BUILD_MIN_MB:-3500}
TURBO_CONCURRENCY=${TURBO_CONCURRENCY:-1}
NODE_MAX_OLD_SPACE_SIZE=${NODE_MAX_OLD_SPACE_SIZE:-1536}
BUILD_THREADS=${BUILD_THREADS:-1}
MIN_DISK_FREE_MB=${MIN_DISK_FREE_MB:-6000}

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
swap_total_mb() { awk '/SwapTotal/ {print int($2/1024)}' /proc/meminfo; }
# available RAM + free swap: what a build can actually grow into
headroom_mb() { awk '/MemAvailable|SwapFree/ {t += $2} END {print int(t/1024)}' /proc/meminfo; }

ensure_swap() {
  if [ "$(swap_total_mb)" -gt 0 ]; then
    log "swap present: $(swap_total_mb)MB"
    return
  fi
  log "no swap -- creating ${SWAP_SIZE_MB}MB /swapfile"
  sudo fallocate -l "${SWAP_SIZE_MB}M" /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count="$SWAP_SIZE_MB"
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  log "swap enabled: $(swap_total_mb)MB"
}

disk_free_mb() { df -Pm / | awk 'NR==2 {print $4}'; }

# Every build leaves GBs of BuildKit cache plus the superseded (now dangling)
# images; left alone they fill the disk within a couple of deploys -- which
# also starves Postgres, not just the next build. Never touches volumes.
cleanup_docker_disk() {
  docker builder prune -af >/dev/null 2>&1 || true
  docker image prune -f >/dev/null 2>&1 || true
  log "docker cleanup done: $(disk_free_mb)MB disk free"
}

require_disk_space() {
  mb=$(disk_free_mb)
  if [ "$mb" -lt "$MIN_DISK_FREE_MB" ]; then
    log "only ${mb}MB disk free -- pruning docker build cache and dangling images"
    cleanup_docker_disk
    mb=$(disk_free_mb)
  fi
  if [ "$mb" -lt "$MIN_DISK_FREE_MB" ]; then
    log "ERROR: only ${mb}MB disk free (need ${MIN_DISK_FREE_MB}MB) -- aborting before the disk fills up." >&2
    exit 1
  fi
}

require_build_headroom() {
  # $1 = service about to be built
  mb=$(headroom_mb)
  if [ "$mb" -lt "$BUILD_MIN_MB" ]; then
    log "ERROR: only ${mb}MB RAM+swap available before building $1 (need ${BUILD_MIN_MB}MB) -- aborting before the host runs out of memory." >&2
    exit 1
  fi
  log "building $1 with ${mb}MB RAM+swap available"
}

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

ensure_swap

# web/space/admin/live/api build from source; worker/beat-worker/migrator
# share api's image (plane-backend:local), so building api covers them too.
BUILD_SERVICES="web space admin live api"
for svc in $BUILD_SERVICES; do
  require_disk_space
  require_build_headroom "$svc"
  if [ "$svc" = "api" ]; then
    $COMPOSE build "$svc"
  else
    $COMPOSE build \
      --build-arg TURBO_CONCURRENCY="$TURBO_CONCURRENCY" \
      --build-arg NODE_MAX_OLD_SPACE_SIZE="$NODE_MAX_OLD_SPACE_SIZE" \
      --build-arg BUILD_THREADS="$BUILD_THREADS" \
      "$svc"
  fi
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

cleanup_docker_disk

log "deploy complete. current status:"
$COMPOSE ps --format "table {{.Name}}\t{{.Status}}"
