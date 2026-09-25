# AppyMonkeys Plane deployment

This is the self-hosted deployment setup for this fork of Plane
(AppyMonkeys/plane, branch `feat/browser-push-notifications`). It builds
`web`/`space`/`admin`/`live`/`api`/`worker`/`beat-worker`/`migrator` from
this repo's own source (not the upstream prebuilt images), so this fork's
changes -- browser push notifications, installable/offline PWA support,
in-app analytics, self-hosted Swagger UI, etc. -- actually ship.

Everything needed to stand this up from a bare clone lives right here:

```
deployments/appymonkeys/
├── docker-compose.yaml   # the whole stack: web, api, db, redis, minio, proxy, backup...
├── .env.example          # copy to .env and fill in
└── backup-scripts/
    ├── backup.sh          # runs inside the `backup` service -- see backup-scripts/README.md
    ├── restore.sh          # one-shot restore, from S3 or a local backup
    └── README.md           # full backup/restore documentation
```

## Quickstart: clone and run

```bash
git clone https://github.com/AppyMonkeys/plane.git
cd plane/deployments/appymonkeys

cp .env.example .env
# edit .env: at minimum set APP_DOMAIN, SECRET_KEY, LIVE_SERVER_SECRET_KEY,
# POSTGRES_PASSWORD, RABBITMQ_PASSWORD (see the comments in .env.example
# for how to generate each one)

docker compose build      # builds web/space/admin/live/api images from source
docker compose up -d      # starts the full stack

# wait ~30s for migrations, then check it's up:
curl -sS http://localhost/           # or http://localhost:$LISTEN_HTTP_PORT/ if you changed the port
```

That's the whole thing. `docker compose ps` shows every container;
`docker compose logs -f api` (or any service name) tails its logs.

## Config notes

- **`APP_DOMAIN`** is whatever hostname/IP this instance is reachable at.
  For a cloud VM, that's its public DNS name or IP; for local dev, your
  LAN IP or `localhost`.
- **TLS**: `proxy` no longer publishes any host port on its own -- see
  **[edge-proxy/README.md](edge-proxy/README.md)**. It's a separate
  shared Caddy container that terminates TLS (Let's Encrypt) for the
  whole host and reverse-proxies to `proxy` (and, on this deployment, to
  docmost as well, at `/docmost`). Bring it up after this stack:
  `cd edge-proxy && docker compose up -d`. TLS matters for more than
  cosmetics here -- Plane's PWA install/offline support
  (`apps/web/public/sw.js`) needs a secure context to register its
  service worker at all; it silently does nothing over plain HTTP.
- **`CUSTOM_BUILD`**: this compose file always builds from source
  regardless of this flag (kept only because some Dockerfiles reference
  it); there's no prebuilt-image mode here.
- **Small disks**: the `uploads` MinIO volume grows with every attachment
  users upload and can reach many GB. Don't assume a host has room to hold
  a _second_ copy of it (e.g. for a local backup file) on top of the live
  volume -- see backup-scripts/README.md for how backups avoid that
  problem by streaming straight to S3.

## Rebuilding after a code change

```bash
docker compose build <service>   # e.g. `docker compose build web`
docker compose up -d <service>   # recreate just that container
```

A plain `docker compose up -d` with no `build` reuses whatever images were
already built -- it does **not** pick up source changes on its own.

### Deploying to a memory-constrained host

`docker compose build && docker compose up -d --build` builds/restarts
everything at once -- fine on a beefy machine, but this has OOM-killed the
stack before on a small box (2 vCPU / ~4GB is what this was developed
against). **`deploy-scripts/deploy.sh <branch>`** does the same end result one
service at a time instead, pausing and checking free memory between every
build and every restart:

```bash
cd deployments/appymonkeys
./deploy-scripts/deploy.sh preview   # pull, build each app one at a time, migrate, restart one at a time
```

See the `deploy-plane` Claude Code skill (`.claude/skills/deploy-plane/`)
for the full checklist around this (backup first, verify after) when an
agent is doing the deploy.

## Backups and restore

See **[backup-scripts/README.md](backup-scripts/README.md)** for the full
story: how the continuous backup loop works, S3 vs. local-fallback mode,
the `FAILED_BACKUP.log` failure record, and every `restore.sh` command
(including full disaster recovery onto a brand-new host).

Quick reference:

```bash
# check backup status
docker logs plane-app-backup-1 --tail 50
cat ./backup/FAILED_BACKUP.log 2>&1 || echo "no failures"

# restore the latest backup from S3
./backup-scripts/restore.sh s3

# restore the latest local backup (only relevant if S3_BACKUP_BUCKET is unset)
./backup-scripts/restore.sh
```
