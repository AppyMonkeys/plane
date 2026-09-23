# Plane backup & restore

Two scripts:

- **`backup.sh`** -- runs continuously inside the `backup` service in
  `docker-compose.yaml`, taking a full backup (Postgres dump + the MinIO
  `uploads` volume) on an interval.
- **`restore.sh`** -- a one-shot script you run by hand to restore a backup,
  from either S3 or a local `backup/<timestamp>/` directory.

## How backup.sh works

Every `BACKUP_INTERVAL_SECONDS` (default `18000` = 5 hours), it:

1. Dumps the `plane` Postgres database with `pg_dump -F c`.
2. Archives the MinIO `uploads` volume with `tar`.
3. Uploads both to S3, then prunes old backups so only the newest
   `S3_BACKUP_KEEP` remain.

**Both steps stream straight into `aws s3 cp -` -- neither the dump nor the
tar is ever written to local disk.** This is deliberate: the live uploads
volume alone can be tens of GB, and a small root volume (this EC2 instance
has 50GB total) doesn't have room for a second on-disk copy of it on top of
everything else already using that disk. Streaming keeps local disk usage
flat no matter how large the backup grows.

If `S3_BACKUP_BUCKET` is **not** set, it falls back to writing
`plane.dump` + `uploads.tar` under `./backup/<timestamp>/` and pruning to
the newest `BACKUP_KEEP` local copies instead. This fallback exists for
local dev machines that don't have an S3 bucket configured -- don't rely
on it in production on a disk too small to hold the uploads volume twice.

### Failure logging

Every failed dump or upload appends one line to `./backup/FAILED_BACKUP.log`
(created only on the first failure) with a timestamp, which part failed,
and the underlying error:

```
2026-09-23T06:43:17+00:00	backup=2026-09-23_06-43-15	target=plane.dump	error=pg_dump rc=0: ; s3 rc=1: upload failed: ... NoSuchBucket ...
```

A backup that fails on one part but succeeds on the other still uploads
what it can -- e.g. if the DB dump succeeds but the uploads tar fails, the
dump is still in S3 and only the tar failure is logged. Check this file if
you suspect backups aren't running cleanly:

```bash
ssh -i ~/.ssh/am-us-west-2.pem ec2-user@<ec2-host> 'cat ~/plane/backup/FAILED_BACKUP.log'
```

No output / file doesn't exist = no failures yet.

### Config (set in `.env`)

| Variable                  | Default   | Meaning                                             |
| ------------------------- | --------- | --------------------------------------------------- |
| `S3_BACKUP_BUCKET`        | _(unset)_ | S3 bucket to stream backups to. Unset = local mode. |
| `S3_BACKUP_PREFIX`        | `plane`   | Key prefix inside the bucket.                       |
| `S3_BACKUP_KEEP`          | `3`       | Max backups kept in S3.                             |
| `BACKUP_INTERVAL_SECONDS` | `18000`   | Seconds between backups (18000s = 5h).              |
| `BACKUP_KEEP`             | `2`       | Max local copies kept when S3 is unset (fallback).  |

The container needs `aws` CLI, which `backup.sh` installs itself on first
run (`apk add aws-cli`) and picks up credentials automatically from the
EC2 instance's IAM role via the metadata service -- no access keys need to
be configured anywhere.

### Checking backup status

```bash
# tail live backup logs
ssh -i ~/.ssh/am-us-west-2.pem ec2-user@<ec2-host> 'docker logs plane-app-backup-1 --tail 50'

# list backups currently in S3
ssh -i ~/.ssh/am-us-west-2.pem ec2-user@<ec2-host> 'aws s3 ls s3://am-toolchain-plane/plane/'

# see the size of a specific backup
ssh -i ~/.ssh/am-us-west-2.pem ec2-user@<ec2-host> 'aws s3 ls s3://am-toolchain-plane/plane/<timestamp>/ --human-readable'

# check for any failed backups
ssh -i ~/.ssh/am-us-west-2.pem ec2-user@<ec2-host> 'cat ~/plane/backup/FAILED_BACKUP.log 2>&1 || echo "no failures"'
```

### Forcing a backup right now (don't wait for the interval)

```bash
ssh -i ~/.ssh/am-us-west-2.pem ec2-user@<ec2-host> 'cd ~/plane && docker compose restart backup'
```

Restarting the container re-runs the loop, which does one backup
immediately on startup before sleeping for the interval again.

## How restore.sh works

`restore.sh` stops the app services (`api worker beat-worker live web admin
space`), stops `plane-minio` (must be stopped before the uploads volume is
overwritten -- see the comment in the script for why), restores the
Postgres dump with `pg_restore --clean --if-exists`, replaces the contents
of the uploads volume with the backup's `uploads.tar`, restarts
`plane-minio` and waits for its health check, then restarts the app
services.

**This overwrites the current database and all uploaded files.** The
script pauses 5 seconds after printing that warning so you can Ctrl+C.

Like `backup.sh`, an S3 restore streams the dump straight into `pg_restore`
and the tar straight into the extraction -- no local copy of either file
is written, for the same disk-space reason.

### Restore from S3 (production)

```bash
ssh -i ~/.ssh/am-us-west-2.pem ec2-user@<ec2-host>
cd ~/plane

# restore the most recent backup in S3
./backup-scripts/restore.sh s3

# restore a specific backup (see `aws s3 ls s3://am-toolchain-plane/plane/` for available timestamps)
./backup-scripts/restore.sh s3 2026-09-23_06-34-36
```

### Restore from a local backup (dev machines / S3-unset mode)

```bash
cd ~/plane

# restore the most recent local backup
./backup-scripts/restore.sh

# restore a specific local backup
./backup-scripts/restore.sh 2026-09-23_06-34-36
```

### Requirements

- Run from the machine with the Plane docker-compose stack (`plane-db` and
  `plane-minio` must be running -- start the stack first with
  `docker compose up -d` if they aren't).
- S3 restore needs the `aws` CLI on that host and either an IAM role (EC2)
  or configured credentials (`aws configure`) that can read the bucket.
- S3 restore reads `S3_BACKUP_BUCKET` / `S3_BACKUP_PREFIX` from `.env` in
  the same directory as `docker-compose.yaml`.

## One-time full disaster-recovery example

If EC2 is destroyed and rebuilt from scratch:

```bash
# 1. get the code onto the new instance and bring the stack up empty
rsync -avz -e "ssh -i ~/.ssh/am-us-west-2.pem" ./ ec2-user@<new-ec2-host>:~/plane/
ssh -i ~/.ssh/am-us-west-2.pem ec2-user@<new-ec2-host>
cd ~/plane
docker compose up -d

# 2. wait for plane-db and plane-minio to be healthy, then restore
./backup-scripts/restore.sh s3
```

That pulls the latest backup straight from `s3://am-toolchain-plane/plane/`
and restores it into the fresh stack.
