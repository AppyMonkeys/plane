# edge-proxy

A shared Caddy container that's the **only thing publishing host ports
80/443** on this box. It terminates TLS (Let's Encrypt, auto-issued per
domain) for two subdomains and reverse-proxies each to its own app:

- `PLANE_DOMAIN` → Plane's own internal proxy (`plane-app-proxy-1:80`,
  which does its own routing to web/api/space/admin/live)
- `DOCMOST_DOMAIN` → docmost (`docmost-docmost-1:3000`)

This exists because Plane and docmost are two separate docker-compose
projects that happen to run on the same host -- only one container can
bind port 443, so whichever one owns it has to front the other. Using a
subdomain per app (rather than path-prefixing one app under the other)
means each gets a clean root path and its own cert, no URL rewriting.

## Why this matters for Plane specifically

Browsers only register a service worker over a **secure context**
(HTTPS, or `localhost`) -- with no exception for a plain-HTTP public
hostname. Plane's PWA install prompt and offline app-shell caching
(`apps/web/public/sw.js`) silently do nothing without this. Getting HTTPS
working via `edge-proxy` is what makes those actually work.

## Requirements

- **Real DNS**: both `PLANE_DOMAIN` and `DOCMOST_DOMAIN` need an A record
  pointing at this host's IP. A bare cloud-provider hostname (e.g.
  `ec2-*.compute.amazonaws.com`) will **not** work -- Let's Encrypt
  refuses to issue certificates for those by policy, not just rate
  limiting. If the host's IP ever changes (e.g. an EC2 stop/start without
  an Elastic IP), update the A records or this breaks again.

## Setup

Prerequisites: both projects already exist (so their networks exist to
join) --

```bash
cd ~/plane/deployments/appymonkeys && docker compose up -d
cd ~/docmost && docker compose up -d
```

Then:

1. **Set `APP_DOMAIN` and `DOCMOST_DOMAIN` in this stack's `.env`** (the
   same file `../docker-compose.yaml` uses -- `edge-proxy` reads both
   from it). `APP_DOMAIN` is Plane's own domain (already required for
   Plane itself); add `DOCMOST_DOMAIN` alongside it, e.g.:

   ```bash
   APP_DOMAIN=tickets.example.com
   DOCMOST_DOMAIN=docs.example.com
   ```

   Also update `WEB_URL` / `CORS_ALLOWED_ORIGINS` in the same `.env` to
   `https://${APP_DOMAIN}` (no port).

2. **Point docmost at its own domain.** Edit
   `~/docmost/docker-compose.yml` (not in this repo -- docmost is a
   separate app/deployment):

   ```yaml
   environment:
     APP_URL: "https://docs.example.com"
   ```

   and remove its `ports: ["80:3000"]` line -- `edge-proxy` is the only
   thing publishing a host port now.

3. **Remove Plane's own port publishing** in
   `../docker-compose.yaml`'s `proxy` service (delete its `ports:`
   block) -- same reasoning, `edge-proxy` fronts it now.

4. **Recreate everything that changed:**

   ```bash
   cd ~/docmost && docker compose up -d docmost
   cd ~/plane/deployments/appymonkeys && docker compose up -d api worker proxy
   ```

5. **Bring up edge-proxy** (symlinking `.env` once means every future
   `docker compose` command here picks it up automatically, no
   `--env-file` flag to remember):

   ```bash
   cd ~/plane/deployments/appymonkeys/edge-proxy
   ln -sf ../.env .env
   docker compose up -d
   ```

   First start takes a few seconds while Caddy requests both Let's
   Encrypt certs. Watch it with `docker logs edge-proxy-caddy-1 -f`.

6. Verify:
   ```bash
   curl -I https://<PLANE_DOMAIN>/     # Plane
   curl -I https://<DOCMOST_DOMAIN>/   # docmost
   ```
