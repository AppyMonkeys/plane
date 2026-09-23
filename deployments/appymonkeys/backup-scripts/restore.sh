#!/bin/sh
# Restore a Plane backup created by backup.sh (pg_dump + uploads.tar), from
# either a local backup/<timestamp>/ directory or directly from S3. Run
# from the plane-app directory (where docker-compose.yaml lives), or from
# anywhere -- it cd's into its own parent directory first.
#
# Both modes stream straight into pg_restore / the uploads volume -- no
# local copy of plane.dump or uploads.tar is ever written for an S3
# restore, since the uploads volume alone can be tens of GB and a small
# disk (see README.md) has no room to stage a second copy of it.
#
# Usage:
#   ./backup-scripts/restore.sh                       # restore latest LOCAL backup
#   ./backup-scripts/restore.sh 2026-08-29_14-45-48    # restore a specific LOCAL backup
#   ./backup-scripts/restore.sh s3                     # restore latest S3 backup
#   ./backup-scripts/restore.sh s3 2026-08-29_14-45-48  # restore a specific S3 backup

set -eu

cd "$(dirname "$0")/.."

if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    COMPOSE_CMD="docker compose"
fi
COMPOSE="$COMPOSE_CMD -f docker-compose.yaml"

BACKUP_ROOT="./backup"
DB_CONTAINER=$($COMPOSE ps -q plane-db)
MINIO_CONTAINER=$($COMPOSE ps -q plane-minio)

if [ -z "$DB_CONTAINER" ]; then
    echo "plane-db container not found/not running. Start the stack first (docker compose up -d)." >&2
    exit 1
fi
if [ -z "$MINIO_CONTAINER" ]; then
    echo "plane-minio container not found/not running. Start the stack first (docker compose up -d)." >&2
    exit 1
fi

# Resolve the actual "uploads" volume name by inspecting the running
# container's mounts, rather than guessing it from the compose project
# name (which can differ from the directory this script lives in).
STORAGE_VOLUME=$(docker inspect "$MINIO_CONTAINER" --format '{{ range .Mounts }}{{ if eq .Destination "/export" }}{{ .Name }}{{ end }}{{ end }}')
if [ -z "$STORAGE_VOLUME" ]; then
    echo "Could not resolve the uploads volume from plane-minio's mounts." >&2
    exit 1
fi

# Pull DB credentials from the db container's own environment so this
# stays in sync with whatever .env says, instead of hardcoding them here.
DB_USER=$(docker exec "$DB_CONTAINER" printenv POSTGRES_USER)
DB_NAME=$(docker exec "$DB_CONTAINER" printenv POSTGRES_DB)
DB_PASSWORD=$(docker exec "$DB_CONTAINER" printenv POSTGRES_PASSWORD)

SOURCE="local"
if [ "${1:-}" = "s3" ]; then
  SOURCE="s3"
  shift
fi
TS="${1:-}"

if [ "$SOURCE" = "s3" ]; then
  if ! command -v aws >/dev/null 2>&1; then
    echo "aws cli not found on this host -- install it first (see README.md)." >&2
    exit 1
  fi
  S3_BUCKET=$(grep -E '^S3_BACKUP_BUCKET=' .env | cut -d= -f2-)
  S3_PREFIX=$(grep -E '^S3_BACKUP_PREFIX=' .env | cut -d= -f2-)
  S3_PREFIX="${S3_PREFIX:-plane}"
  if [ -z "$S3_BUCKET" ]; then
    echo "S3_BACKUP_BUCKET is not set in .env -- can't restore from S3." >&2
    exit 1
  fi

  if [ -z "$TS" ]; then
    TS=$(aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix "${S3_PREFIX}/" --delimiter / \
          --query 'CommonPrefixes[].Prefix' --output text 2>/dev/null \
          | tr '\t' '\n' | sed "s#^${S3_PREFIX}/##; s#/\$##" | sort | tail -1)
    if [ -z "$TS" ]; then
      echo "No backups found under s3://${S3_BUCKET}/${S3_PREFIX}/" >&2
      exit 1
    fi
    echo "No timestamp given, using most recent S3 backup: $TS"
  fi

  DUMP_URL="s3://${S3_BUCKET}/${S3_PREFIX}/${TS}/plane.dump"
  STORAGE_URL="s3://${S3_BUCKET}/${S3_PREFIX}/${TS}/uploads.tar"
  if ! aws s3 ls "$DUMP_URL" >/dev/null 2>&1 || ! aws s3 ls "$STORAGE_URL" >/dev/null 2>&1; then
    echo "Backup files not found at s3://${S3_BUCKET}/${S3_PREFIX}/${TS}/" >&2
    exit 1
  fi
  echo "Restoring from $DUMP_URL and $STORAGE_URL"
else
  if [ -z "$TS" ]; then
    TS=$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort | tail -1)
    if [ -z "$TS" ]; then
      echo "No backups found under $BACKUP_ROOT" >&2
      exit 1
    fi
    echo "No timestamp given, using most recent local backup: $TS"
  fi

  DEST="$BACKUP_ROOT/$TS"
  DUMP="$DEST/plane.dump"
  STORAGE="$DEST/uploads.tar"
  if [ ! -f "$DUMP" ] || [ ! -f "$STORAGE" ]; then
    echo "Backup files not found in $DEST" >&2
    exit 1
  fi
  echo "Restoring from $DEST"
fi

echo "This will OVERWRITE the current database and uploaded files. Ctrl+C now to abort."
sleep 5

echo "[restore] stopping app services..."
$COMPOSE stop api worker beat-worker live web admin space

# plane-minio must be stopped too -- it holds the uploads volume mounted
# live, and wiping/untarring into that volume out from under a running
# MinIO leaves its in-memory state pointing at a format.json that no
# longer matches what's on disk ("UUID ... inconsistent drive found"),
# which breaks reads/writes until the container is restarted. Stopping it
# first avoids that entirely.
echo "[restore] stopping plane-minio..."
$COMPOSE stop plane-minio

echo "[restore] restoring database..."
if [ "$SOURCE" = "s3" ]; then
  aws s3 cp "$DUMP_URL" - | docker exec -i -e PGPASSWORD="$DB_PASSWORD" "$DB_CONTAINER" \
    pg_restore -U "$DB_USER" -d "$DB_NAME" --clean --if-exists --no-owner
else
  docker cp "$DUMP" "$DB_CONTAINER":/tmp/restore.dump
  docker exec -e PGPASSWORD="$DB_PASSWORD" "$DB_CONTAINER" pg_restore -U "$DB_USER" -d "$DB_NAME" --clean --if-exists --no-owner /tmp/restore.dump
  docker exec "$DB_CONTAINER" rm /tmp/restore.dump
fi

echo "[restore] restoring uploads..."
if [ "$SOURCE" = "s3" ]; then
  aws s3 cp "$STORAGE_URL" - | docker run --rm -i \
    -v "$STORAGE_VOLUME":/target \
    alpine sh -c "rm -rf /target/* /target/..?* /target/.[!.]* 2>/dev/null; tar -xf - -C /target"
else
  docker run --rm \
    -v "$STORAGE_VOLUME":/target \
    -v "$(pwd)/$DEST":/src:ro \
    alpine sh -c "rm -rf /target/* /target/..?* /target/.[!.]* 2>/dev/null; tar -xf /src/uploads.tar -C /target"
fi

echo "[restore] starting plane-minio..."
$COMPOSE start plane-minio

# Give MinIO a moment to come up clean before pointing the app services at
# it again, instead of racing api/worker's own startup against it.
attempt=1
max_attempts=15
until docker exec "$MINIO_CONTAINER" curl -sf http://localhost:9000/minio/health/live >/dev/null 2>&1; do
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "[restore] plane-minio did not report healthy after ${max_attempts}s -- check 'docker logs $MINIO_CONTAINER' before continuing." >&2
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done

echo "[restore] starting app services..."
$COMPOSE start api worker beat-worker live web admin space

echo "[restore] done."
