# Plane backup & restore

Two scripts:

- **`run-backup.sh`** -- a one-shot backup, meant to be run by **cron on
  the EC2 host** (not as a docker-compose service). Stops the app stack,
  backs up, restarts it "slowly slowly".
- **`restore.sh`** -- a one-shot script you run by hand to restore a
  backup, from either S3 or a local `backup/<timestamp>/` directory.

## How run-backup.sh works

It cannot run _inside_ docker-compose as a service, because it needs to
`docker compose stop`/`start` the rest of the stack -- a container can't
stop its own compose project out from under itself. It's triggered by a
**cron job on the host** instead:

```bash
crontab -l   # should contain, every 5 hours:
0 */5 * * * /home/ec2-user/plane/plane-src/deployments/appymonkeys/backup-scripts/run-backup.sh >> /home/ec2-user/plane/plane-src/deployments/appymonkeys/backup/cron.log 2>&1
```

Each run does, in order:

1. **Stop everything except `plane-db`** -- `web`, `space`, `admin`,
   `live`, `api`, `worker`, `beat-worker`, `proxy`, `plane-minio`,
   `plane-redis`, `plane-mq`. `plane-db` stays up because `pg_dump` needs
   it; the uploads tar reads the volume directly off disk, so
   `plane-minio` doesn't need to be running for that part. **The site is
   unreachable for the duration of the backup** (a few minutes).

   This exists because running the dump+tar+upload _alongside_ the live
   app was itself a resource-contention risk on this box: the old
   always-on `backup` container spiked to ~700MB of RAM mid-upload, on a
   host that sits at well under 200MB free even at idle, and this box has
   already OOM'd once under combined load.

2. **Dump + archive, streamed straight to S3.** `pg_dump` and `tar` both
   pipe directly into `aws s3 cp -` -- neither ever touches local disk.
   This isn't optional: the uploads volume alone can be tens of GB, and a
   small disk has no room to stage a second copy of it (see the note in
   the top-level README.md). Failures are recorded to
   `./backup/FAILED_BACKUP.log` with a timestamp, which part failed, and
   the underlying error -- check it if you suspect a backup didn't run
   cleanly.

3. **Prune S3** to the newest `S3_BACKUP_KEEP` backups.

4. **Restart every service one at a time** ("slowly slowly"), in
   dependency order (`plane-redis` → `plane-mq` → `plane-minio` → `api` →
   `worker` → `beat-worker` → `web` → `admin` → `space` → `live` →
   `proxy`), pausing 10s and checking `MemAvailable` after each one. If
   free memory drops under 150MB it pauses another 20s before continuing,
   rather than piling the next container on top of a box that's already
   under pressure -- this is what protects against the OOM that happened
   when several heavy containers came up under load simultaneously.

### Config (read from `.env`)

| Variable           | Default      | Meaning                                                                                         |
| ------------------ | ------------ | ----------------------------------------------------------------------------------------------- |
| `S3_BACKUP_BUCKET` | _(required)_ | S3 bucket to stream backups to. No local-storage fallback -- the script exits if this is unset. |
| `S3_BACKUP_PREFIX` | `plane`      | Key prefix inside the bucket.                                                                   |
| `S3_BACKUP_KEEP`   | `3`          | Max backups kept in S3.                                                                         |

Needs the `aws` CLI on the host (already present on this EC2 image) and
credentials -- picked up automatically from the instance's IAM role via
the metadata service, no access keys configured anywhere.

### Checking backup status

```bash
# tail the most recent cron run
ssh -i ~/.ssh/am-us-west-2.pem ec2-user@<ec2-host> 'tail -n 60 ~/plane/plane-src/deployments/appymonkeys/backup/cron.log'

# list backups currently in S3
ssh -i ~/.ssh/am-us-west-2.pem ec2-user@<ec2-host> 'aws s3 ls s3://am-toolchain-plane/plane/'

# check for any failed backups
ssh -i ~/.ssh/am-us-west-2.pem ec2-user@<ec2-host> 'cat ~/plane/plane-src/deployments/appymonkeys/backup/FAILED_BACKUP.log 2>&1 || echo "no failures"'
```

### Running a backup right now (don't wait for cron)

```bash
ssh -i ~/.ssh/am-us-west-2.pem ec2-user@<ec2-host>
cd ~/plane/plane-src/deployments/appymonkeys
./backup-scripts/run-backup.sh
```

This stops the site while it runs -- don't run it casually during active
use.

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

Like `run-backup.sh`, an S3 restore streams the dump straight into
`pg_restore` and the tar straight into the extraction -- no local copy of
either file is written, for the same disk-space reason.

### Restore from S3 (production)

```bash
ssh -i ~/.ssh/am-us-west-2.pem ec2-user@<ec2-host>
cd ~/plane/plane-src/deployments/appymonkeys

# restore the most recent backup in S3
./backup-scripts/restore.sh s3

# restore a specific backup (see `aws s3 ls s3://am-toolchain-plane/plane/` for available timestamps)
./backup-scripts/restore.sh s3 2026-09-23_06-34-36
```

### Restore from a local backup (dev machines)

```bash
cd ~/plane/plane-src/deployments/appymonkeys

# restore the most recent local backup
./backup-scripts/restore.sh

# restore a specific local backup
./backup-scripts/restore.sh 2026-09-23_06-34-36
```

(`restore.sh` still supports local `backup/<timestamp>/` directories for
dev use -- only `run-backup.sh`, the production path, requires S3.)

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
ssh -i ~/.ssh/am-us-west-2.pem ec2-user@<new-ec2-host>
git clone -b feat/browser-push-notifications https://github.com/AppyMonkeys/plane.git ~/plane/plane-src
cd ~/plane/plane-src/deployments/appymonkeys
cp .env.example .env   # fill in real values -- see the top-level README.md
docker compose up -d

# 2. wait for plane-db and plane-minio to be healthy, then restore
./backup-scripts/restore.sh s3

# 3. re-add the cron job for future backups
crontab -e
# 0 */5 * * * /home/ec2-user/plane/plane-src/deployments/appymonkeys/backup-scripts/run-backup.sh >> /home/ec2-user/plane/plane-src/deployments/appymonkeys/backup/cron.log 2>&1
```

That pulls the latest backup straight from `s3://am-toolchain-plane/plane/`
and restores it into the fresh stack.
