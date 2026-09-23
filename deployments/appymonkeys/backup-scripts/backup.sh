#!/bin/sh
# Continuous backup loop for Plane: dumps plane-db (pg_dump) and archives the
# minio "uploads" volume (tar), on an interval.
#
# When S3_BACKUP_BUCKET is set, both are streamed directly into S3 (pg_dump
# and tar piped straight into `aws s3 cp -`) -- no local copy is ever
# written. This matters because the live uploads volume alone can be tens
# of GB, so a disk that holds that volume plus a second local backup copy
# of it doesn't have room to spare; streaming keeps local disk usage flat
# regardless of backup size. Every failed upload/dump is recorded to
# $FAILED_LOG with a timestamp and the underlying error. S3 objects are
# pruned to the newest $S3_KEEP. Modeled on docmost's backup service.
#
# When S3_BACKUP_BUCKET is unset (e.g. local dev), it falls back to writing
# dump+tar under $BACKUP_ROOT and pruning to the newest $KEEP local copies.
set -u

BACKUP_ROOT=/backup
FAILED_LOG="${BACKUP_ROOT}/FAILED_BACKUP.log"
KEEP=${BACKUP_KEEP:-2}
INTERVAL_SECONDS=${BACKUP_INTERVAL_SECONDS:-18000}
S3_BUCKET=${S3_BACKUP_BUCKET:-}
S3_PREFIX=${S3_BACKUP_PREFIX:-plane}
S3_KEEP=${S3_BACKUP_KEEP:-3}

mkdir -p "$BACKUP_ROOT"

if [ -n "$S3_BUCKET" ] && ! command -v aws >/dev/null 2>&1; then
  echo "[backup] installing aws-cli..."
  apk add --no-cache aws-cli >/dev/null 2>&1
fi

log_failure() {
  # $1 = which part failed, $2 = error detail
  printf '%s\tbackup=%s\ttarget=%s\terror=%s\n' "$(date -Iseconds)" "$ts" "$1" "$2" >> "$FAILED_LOG"
}

if [ -n "$S3_BUCKET" ]; then
  echo "[backup] starting loop: every ${INTERVAL_SECONDS}s, streaming directly to s3://${S3_BUCKET}/${S3_PREFIX}, failures logged to ${FAILED_LOG}, keeping last ${S3_KEEP} in S3"
else
  echo "[backup] starting loop: every ${INTERVAL_SECONDS}s, keep last ${KEEP} local copies in ${BACKUP_ROOT}"
fi

prune_s3() {
  s3_dirs=$(aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix "${S3_PREFIX}/" --delimiter / --query 'CommonPrefixes[].Prefix' --output text 2>/dev/null | tr '\t' '\n' | sort)
  s3_count=$(printf '%s\n' "$s3_dirs" | grep -c .)
  if [ "$s3_count" -gt "$S3_KEEP" ]; then
    printf '%s\n' "$s3_dirs" | head -n -"$S3_KEEP" | while read -r old; do
      [ -n "$old" ] || continue
      echo "[backup] $(date -Iseconds) pruning old s3 backup: s3://${S3_BUCKET}/${old}"
      aws s3 rm "s3://${S3_BUCKET}/${old}" --recursive >/dev/null
    done
  fi
}

while true; do
  ts=$(date +%Y-%m-%d_%H-%M-%S)

  if [ -n "$S3_BUCKET" ]; then
    work_dir=$(mktemp -d)
    echo "[backup] $(date -Iseconds) starting backup -> s3://${S3_BUCKET}/${S3_PREFIX}/${ts}/"

    # --- database dump, piped straight into the S3 upload, never touches disk ---
    { PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h "$PGHOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -F c 2>"$work_dir/db_pg.err"; echo $? > "$work_dir/db_pg.rc"; } \
      | aws s3 cp - "s3://${S3_BUCKET}/${S3_PREFIX}/${ts}/plane.dump" 2>"$work_dir/db_s3.err"
    db_s3_rc=$?
    db_pg_rc=$(cat "$work_dir/db_pg.rc" 2>/dev/null || echo 1)

    db_ok=0
    if [ "$db_pg_rc" -eq 0 ] && [ "$db_s3_rc" -eq 0 ]; then
      db_ok=1
      echo "[backup] $(date -Iseconds) database dump streamed to S3 OK"
    else
      echo "[backup] $(date -Iseconds) database dump/upload FAILED (pg_dump rc=$db_pg_rc, s3 rc=$db_s3_rc)" >&2
      err_detail="pg_dump rc=${db_pg_rc}: $(tail -c 500 "$work_dir/db_pg.err" 2>/dev/null | tr '\n' ' '); s3 rc=${db_s3_rc}: $(tail -c 500 "$work_dir/db_s3.err" 2>/dev/null | tr '\n' ' ')"
      log_failure "plane.dump" "$err_detail"
    fi

    # --- storage archive, piped straight into the S3 upload ---
    # tar exit codes: 0 = clean, 1 = non-fatal ("file changed as we read it" --
    # e.g. an upload in progress), >=2 = fatal. Retry the whole
    # tar+upload pipeline a few times to try to catch a quiet moment. No -z:
    # attachments are already-compressed images/video, so gzip buys almost
    # nothing while burning a lot of time.
    attempt=1
    max_attempts=3
    storage_ok=0
    tar_rc=1
    storage_s3_rc=1
    while [ "$attempt" -le "$max_attempts" ]; do
      { tar -cf - -C /source_storage . 2>"$work_dir/storage_tar.err"; echo $? > "$work_dir/storage_tar.rc"; } \
        | aws s3 cp - "s3://${S3_BUCKET}/${S3_PREFIX}/${ts}/uploads.tar" 2>"$work_dir/storage_s3.err"
      storage_s3_rc=$?
      tar_rc=$(cat "$work_dir/storage_tar.rc" 2>/dev/null || echo 1)

      if [ "$storage_s3_rc" -eq 0 ] && [ "$tar_rc" -le 1 ]; then
        storage_ok=1
        if [ "$tar_rc" -eq 0 ]; then
          echo "[backup] $(date -Iseconds) storage archive streamed to S3 OK"
        else
          echo "[backup] $(date -Iseconds) storage archive streamed to S3 OK (some files changed during read, see attempt $attempt)"
        fi
        break
      fi

      if [ "$attempt" -lt "$max_attempts" ]; then
        echo "[backup] $(date -Iseconds) storage archive/upload attempt $attempt failed (tar rc=$tar_rc, s3 rc=$storage_s3_rc), retrying..."
        attempt=$((attempt + 1))
        sleep 2
        continue
      fi
      break
    done

    if [ "$storage_ok" -ne 1 ]; then
      echo "[backup] $(date -Iseconds) storage archive/upload FAILED after $attempt attempt(s) (tar rc=$tar_rc, s3 rc=$storage_s3_rc)" >&2
      err_detail="tar rc=${tar_rc}: $(tail -c 500 "$work_dir/storage_tar.err" 2>/dev/null | tr '\n' ' '); s3 rc=${storage_s3_rc}: $(tail -c 500 "$work_dir/storage_s3.err" 2>/dev/null | tr '\n' ' ')"
      log_failure "uploads.tar" "$err_detail"
    fi

    rm -rf "$work_dir"

    if [ "$db_ok" -eq 1 ] && [ "$storage_ok" -eq 1 ]; then
      echo "[backup] $(date -Iseconds) backup ${ts} complete"
    else
      echo "[backup] $(date -Iseconds) backup ${ts} incomplete -- see ${FAILED_LOG}" >&2
    fi

    prune_s3
  else
    dest="${BACKUP_ROOT}/${ts}"
    mkdir -p "$dest"

    echo "[backup] $(date -Iseconds) starting backup -> $dest"

    if PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h "$PGHOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -F c -f "$dest/plane.dump"; then
      echo "[backup] $(date -Iseconds) database dump OK"
    else
      echo "[backup] $(date -Iseconds) database dump FAILED" >&2
      log_failure "plane.dump" "pg_dump rc=$?"
    fi

    attempt=1
    max_attempts=3
    tar_rc=1
    while [ "$attempt" -le "$max_attempts" ]; do
      tar -cf "$dest/uploads.tar" -C /source_storage . 2> "$dest/uploads.tar.stderr"
      tar_rc=$?
      if [ "$tar_rc" -eq 0 ]; then
        break
      fi
      if [ "$attempt" -lt "$max_attempts" ]; then
        echo "[backup] $(date -Iseconds) storage archive attempt $attempt got rc=$tar_rc, retrying..."
        attempt=$((attempt + 1))
        sleep 2
        continue
      fi
      break
    done

    if [ "$tar_rc" -eq 0 ]; then
      echo "[backup] $(date -Iseconds) storage archive OK"
      rm -f "$dest/uploads.tar.stderr"
    elif [ "$tar_rc" -eq 1 ]; then
      echo "[backup] $(date -Iseconds) storage archive OK (some files changed during read after $attempt attempt(s) -- see uploads.tar.stderr)"
    else
      echo "[backup] $(date -Iseconds) storage archive FAILED (exit $tar_rc) after $attempt attempt(s)" >&2
      log_failure "uploads.tar" "tar rc=$tar_rc: $(tail -c 500 "$dest/uploads.tar.stderr" 2>/dev/null | tr '\n' ' ')"
    fi

    # prune: keep only the most recent $KEEP backup folders
    count=$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d | wc -l)
    if [ "$count" -gt "$KEEP" ]; then
      find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d | sort | head -n -"$KEEP" | while read -r old; do
        echo "[backup] $(date -Iseconds) pruning old backup: $old"
        rm -rf "$old"
      done
    fi
  fi

  sleep "$INTERVAL_SECONDS"
done
