#!/bin/sh
# One-shot backup, meant to be run by cron on the EC2 HOST (not as a
# docker-compose service) -- a container can't docker-compose-stop its own
# stack, and this box is memory/CPU constrained enough that running the
# dump+tar+upload *alongside* the live app was itself a contention risk
# (the old always-on `backup` container spiked to ~700MB mid-upload).
#
# Sequence:
#   1. stop every service except plane-db (pg_dump needs it; the uploads
#      tar reads the volume directly, no minio process required)
#   2. pg_dump + tar, both piped straight into `aws s3 cp -` -- no local
#      copy of either is ever written (see README.md for why: this box's
#      disk can't hold a second copy of the uploads volume)
#   3. prune S3 to the newest S3_BACKUP_KEEP
#   4. restart services one at a time ("slowly slowly"), pausing and
#      checking free memory between each, instead of bringing everything
#      up at once -- this box OOM'd once already when several heavy
#      containers started under load simultaneously
#
# Cron entry (every 5 hours):
#   0 */5 * * * /home/ec2-user/plane/backup-scripts/run-backup.sh >> /home/ec2-user/plane/backup/cron.log 2>&1
set -u

cd "$(dirname "$0")/.."

if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    COMPOSE_CMD="docker compose"
fi
COMPOSE="$COMPOSE_CMD -f docker-compose.yaml"

BACKUP_ROOT="./backup"
FAILED_LOG="${BACKUP_ROOT}/FAILED_BACKUP.log"
mkdir -p "$BACKUP_ROOT"

S3_BUCKET=$(grep -E '^S3_BACKUP_BUCKET=' .env | cut -d= -f2-)
S3_PREFIX=$(grep -E '^S3_BACKUP_PREFIX=' .env | cut -d= -f2-)
S3_PREFIX="${S3_PREFIX:-plane}"
S3_KEEP=$(grep -E '^S3_BACKUP_KEEP=' .env | cut -d= -f2-)
S3_KEEP="${S3_KEEP:-3}"

if [ -z "$S3_BUCKET" ]; then
  echo "[backup] S3_BACKUP_BUCKET not set in .env -- aborting (this script has no local-storage mode)." >&2
  exit 1
fi
if ! command -v aws >/dev/null 2>&1; then
  echo "[backup] aws cli not found on this host -- install it first (see README.md)." >&2
  exit 1
fi

DB_CONTAINER=$($COMPOSE ps -q plane-db)
if [ -z "$DB_CONTAINER" ]; then
  echo "[backup] plane-db is not running -- can't back up, skipping this cycle." >&2
  exit 1
fi
DB_USER=$(docker exec "$DB_CONTAINER" printenv POSTGRES_USER)
DB_NAME=$(docker exec "$DB_CONTAINER" printenv POSTGRES_DB)
DB_PASSWORD=$(docker exec "$DB_CONTAINER" printenv POSTGRES_PASSWORD)

MINIO_CONTAINER=$($COMPOSE ps -q plane-minio)
STORAGE_VOLUME=$(docker inspect "$MINIO_CONTAINER" --format '{{ range .Mounts }}{{ if eq .Destination "/export" }}{{ .Name }}{{ end }}{{ end }}')
if [ -z "$STORAGE_VOLUME" ]; then
  echo "[backup] could not resolve the uploads volume from plane-minio's mounts." >&2
  exit 1
fi

ts=$(date +%Y-%m-%d_%H-%M-%S)
log_failure() {
  # $1 = which part failed, $2 = error detail
  printf '%s\tbackup=%s\ttarget=%s\terror=%s\n' "$(date -Iseconds)" "$ts" "$1" "$2" >> "$FAILED_LOG"
}

# Everything except plane-db. plane-redis/plane-mq included too, so the
# box is as idle as possible for the dump+tar+upload window.
STOP_SERVICES="web space admin live api worker beat-worker proxy plane-minio plane-redis plane-mq"
# Restart order: dependencies first.
START_ORDER="plane-redis plane-mq plane-minio api worker beat-worker web admin space live proxy"

echo "[backup] $(date -Iseconds) starting backup ${ts} -- stopping app services"
$COMPOSE stop $STOP_SERVICES

work_dir=$(mktemp -d)

echo "[backup] $(date -Iseconds) dumping database..."
{ docker exec -e PGPASSWORD="$DB_PASSWORD" "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" -F c 2>"$work_dir/db_pg.err"; echo $? > "$work_dir/db_pg.rc"; } \
  | aws s3 cp - "s3://${S3_BUCKET}/${S3_PREFIX}/${ts}/plane.dump" 2>"$work_dir/db_s3.err"
db_s3_rc=$?
db_pg_rc=$(cat "$work_dir/db_pg.rc" 2>/dev/null || echo 1)

db_ok=0
if [ "$db_pg_rc" -eq 0 ] && [ "$db_s3_rc" -eq 0 ]; then
  db_ok=1
  echo "[backup] $(date -Iseconds) database dump streamed to S3 OK"
else
  echo "[backup] $(date -Iseconds) database dump/upload FAILED (pg_dump rc=$db_pg_rc, s3 rc=$db_s3_rc)" >&2
  log_failure "plane.dump" "pg_dump rc=${db_pg_rc}: $(tail -c 500 "$work_dir/db_pg.err" 2>/dev/null | tr '\n' ' '); s3 rc=${db_s3_rc}: $(tail -c 500 "$work_dir/db_s3.err" 2>/dev/null | tr '\n' ' ')"
fi

echo "[backup] $(date -Iseconds) archiving uploads (plane-minio is stopped, reading the volume directly)..."
{ docker run --rm -v "$STORAGE_VOLUME":/source_storage:ro alpine tar -cf - -C /source_storage . 2>"$work_dir/storage_tar.err"; echo $? > "$work_dir/storage_tar.rc"; } \
  | aws s3 cp - "s3://${S3_BUCKET}/${S3_PREFIX}/${ts}/uploads.tar" 2>"$work_dir/storage_s3.err"
storage_s3_rc=$?
tar_rc=$(cat "$work_dir/storage_tar.rc" 2>/dev/null || echo 1)

# tar rc 0 = clean, 1 = non-fatal ("file changed as we read it"). Not
# retried here (unlike the old always-on loop) -- plane-minio is stopped
# and nothing else has the volume mounted read-write, so there's nothing
# to race against; a rc=1 would mean something unexpected touched it.
storage_ok=0
if [ "$storage_s3_rc" -eq 0 ] && [ "$tar_rc" -le 1 ]; then
  storage_ok=1
  echo "[backup] $(date -Iseconds) storage archive streamed to S3 OK"
else
  echo "[backup] $(date -Iseconds) storage archive/upload FAILED (tar rc=$tar_rc, s3 rc=$storage_s3_rc)" >&2
  log_failure "uploads.tar" "tar rc=${tar_rc}: $(tail -c 500 "$work_dir/storage_tar.err" 2>/dev/null | tr '\n' ' '); s3 rc=${storage_s3_rc}: $(tail -c 500 "$work_dir/storage_s3.err" 2>/dev/null | tr '\n' ' ')"
fi

rm -rf "$work_dir"

# prune S3: keep only the newest $S3_KEEP timestamped prefixes
s3_dirs=$(aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix "${S3_PREFIX}/" --delimiter / --query 'CommonPrefixes[].Prefix' --output text 2>/dev/null | tr '\t' '\n' | sort)
s3_count=$(printf '%s\n' "$s3_dirs" | grep -c .)
if [ "$s3_count" -gt "$S3_KEEP" ]; then
  printf '%s\n' "$s3_dirs" | head -n -"$S3_KEEP" | while read -r old; do
    [ -n "$old" ] || continue
    echo "[backup] $(date -Iseconds) pruning old s3 backup: s3://${S3_BUCKET}/${old}"
    aws s3 rm "s3://${S3_BUCKET}/${old}" --recursive >/dev/null
  done
fi

echo "[backup] $(date -Iseconds) restarting app services slowly..."
for svc in $START_ORDER; do
  echo "[backup] $(date -Iseconds) starting $svc"
  $COMPOSE start "$svc"
  sleep 10
  free_mb=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
  echo "[backup] $(date -Iseconds) after $svc: ${free_mb}MB available"
  if [ "$free_mb" -lt 150 ]; then
    echo "[backup] $(date -Iseconds) low memory (${free_mb}MB) after starting $svc -- pausing 20s before continuing" >&2
    sleep 20
  fi
done

if [ "$db_ok" -eq 1 ] && [ "$storage_ok" -eq 1 ]; then
  echo "[backup] $(date -Iseconds) backup ${ts} complete, stack restarted"
else
  echo "[backup] $(date -Iseconds) backup ${ts} incomplete -- see ${FAILED_LOG} -- stack restarted anyway" >&2
fi
