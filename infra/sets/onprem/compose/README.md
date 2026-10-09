# On-prem set: Compose + Traefik

The on-prem set is what the adapter puts on a user's server. This folder holds
the shared proxy (`traefik/`). The per-app Compose template will be added here
once the deploy spec is settled.

```
browser -> DNS (*.<env-id>.onprem.<domain>) -> server :443 -> Traefik -> app container
```

Everything below was first run by hand; the adapter will automate it.
`../test/whoami/` is a throwaway stand-in app used only to prove this path
works. It is not part of the set.

Layout on the server (the `deploy` account owns `/opt/apps`):

```
/opt/apps/traefik/   compose.yaml  .env
/opt/apps/whoami/    compose.yaml  .env     (test only)
```

## 1. Copy to the server (from the service server, as ec2-user)

Run from `infra/sets/onprem/`:

```bash
scp -i ~/.ssh/onprem_deploy -r compose/traefik test/whoami deploy@<VM_IP>:/opt/apps/
```

## 2. Start Traefik (on the server, as deploy)

```bash
cd /opt/apps/traefik
cp .env.example .env          # then set ACME_EMAIL
docker compose up -d
```

## 3. Start the test app

```bash
cd /opt/apps/whoami
cp .env.example .env          # APP_HOST must match the DNS wildcard
docker compose up -d
```

## 4. Verify (staging CA)

Staging certificates are not trusted by browsers, so use `-k` to test:

```bash
curl -k https://whoami.demo.onprem.anyship.cloud
docker compose -f /opt/apps/traefik/compose.yaml logs traefik | grep -i acme
```

A response from whoami means DNS, ports, Traefik and the container are wired
correctly. Staging has generous limits, so repeat freely.

## 5. Switch to the production CA (browser-trusted certificate)

Only after step 4 works. The staging certificate is stored in the
`letsencrypt` volume and would be reused, so it must be removed first.

```bash
cd /opt/apps/traefik
# set ACME_CA_SERVER=https://acme-v02.api.letsencrypt.org/directory in .env
docker compose down
docker volume rm traefik_letsencrypt     # volume name = <folder>_letsencrypt
docker compose up -d
```

Production limits are strict (for example 5 duplicate certificates per week
and 5 failed validations per hostname per hour). Do not loop on failures here.
Keep the `letsencrypt` volume afterwards: losing it means re-issuing.

## Notes

- Compose files hold no secrets. `.env` holds only the contact e-mail and the
  host name, but is still not committed.
- Traefik reads the Docker socket read-only. Whoever controls Traefik can see
  container metadata; a docker-socket-proxy is the hardening step.
- A real app uses the same shape as `test/whoami/`: image, internal port, Host
  rule.
