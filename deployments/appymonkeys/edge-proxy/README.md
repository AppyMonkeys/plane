# edge-proxy

A shared Caddy container that's the **only thing publishing host ports
80/443** on this box. It terminates TLS (Let's Encrypt, auto-issued for
`APP_DOMAIN`) for the one shared hostname and fans out by path:

- `/docmost*` → docmost (`docmost-docmost-1:3000`, prefix stripped)
- everything else → Plane's own internal proxy (`plane-app-proxy-1:80`,
  which does its own routing to web/api/space/admin/live)

This exists because Plane and docmost are two separate docker-compose
projects that happened to end up on the same host/hostname -- only one
container can bind port 443, so whichever one owns it has to front the
other. `edge-proxy` is that front door; neither app's own compose file
publishes 80/443 anymore.

## Why this matters for Plane specifically

Browsers only register a service worker over a **secure context**
(HTTPS, or `localhost`) -- with no exception for a plain-HTTP public
hostname. Plane's PWA install prompt and offline app-shell caching
(`apps/web/public/sw.js`) silently do nothing without this. Getting HTTPS
working via `edge-proxy` is what makes those actually work.

## Setup

Prerequisites: both projects already exist (so their networks exist to
join) --

```bash
cd ~/plane/deployments/appymonkeys && docker compose up -d
cd ~/docmost && docker compose up -d
```

Then:

1. **Stop docmost from publishing its own port 80.** Edit
   `~/docmost/docker-compose.yml`, remove the `docmost` service's
   `ports: ["80:3000"]`, and update `APP_URL` to route through the
   `/docmost` prefix over HTTPS:

   ```yaml
   environment:
     APP_URL: "https://<your-domain-or-AWS-hostname>/docmost"
   ```

   (This isn't in this repo -- docmost is a separate app/deployment. Edit
   it directly wherever `~/docmost/docker-compose.yml` lives.)

2. **Set `APP_DOMAIN` in this stack's `.env`** (the same file
   `../docker-compose.yaml` uses) to the hostname both apps share --
   already required for Plane itself, `edge-proxy` reads the same value.

3. **Recreate docmost** so the port removal + new `APP_URL` take effect:

   ```bash
   cd ~/docmost && docker compose up -d
   ```

4. **Bring up edge-proxy:**

   ```bash
   cd ~/plane/deployments/appymonkeys/edge-proxy
   docker compose up -d
   ```

   First start takes a few seconds while Caddy requests the Let's Encrypt
   cert. Watch it with `docker logs edge-proxy-caddy-1 -f`.

5. Verify:
   ```bash
   curl -I https://<APP_DOMAIN>/           # Plane
   curl -I https://<APP_DOMAIN>/docmost    # docmost
   ```

## Caveats

- **Using a bare AWS hostname (`ec2-*.compute.amazonaws.com`) instead of
  a real domain**: Let's Encrypt can issue a cert for it (it's a real
  public DNS name), but the cert breaks every time the instance stops and
  starts, since EC2 assigns a _new_ public hostname each time (this has
  already happened twice in this deployment's history). A real domain
  with an A record pointed at this instance's IP -- or better, an Elastic
  IP so the address itself stays fixed -- avoids re-doing this setup on
  every restart.
- **docmost under `/docmost`**: `handle_path` strips the prefix before
  forwarding, so docmost's backend sees ordinary root-relative requests.
  Whether its frontend generates asset/link URLs correctly under a
  subpath depends on `APP_URL` being set to include `/docmost` (step 1
  above) -- docmost reads that to build its own absolute URLs. If you see
  broken asset loads or login redirects after switching this on, that's
  the first thing to check.
