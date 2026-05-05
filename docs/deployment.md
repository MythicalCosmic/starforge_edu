# Deployment

v1 ships with a working compose stack for dev. Real production deployment
is out of scope for v1, but the shape is:

| Service | Container | Ports |
|---|---|---|
| Web (HTTP) | gunicorn + `config.wsgi` | 8000 |
| Realtime (ASGI) | daphne + `config.asgi` | 8001 |
| Worker | celery worker | — |
| Beat | celery beat | — |
| Postgres | 16+ (managed) | 5432 |
| Redis | 7+ (managed) | 6379 |
| Object storage | AWS S3 (prod) / MinIO (self-host) | — |
| Reverse proxy | nginx / traefik / caddy | 80/443 |

## Subdomain TLS
For `*.starforge.uz`, use a wildcard cert via Let's Encrypt DNS-01
(certbot with the relevant DNS plugin, or the cert-manager DNS01
solver on Kubernetes). HTTP-01 cannot issue wildcards.

## Secret management
`.env` for dev only. In prod use the platform's secret manager (AWS SSM,
Vault, k8s secrets) and inject as env vars matching the `env(...)` keys
in `config/settings/base.py`.

## Migrations
```bash
python manage.py migrate_schemas --shared           # public schema
python manage.py migrate_schemas                    # all tenant schemas
```

Adding a tenant runs all `TENANT_APPS` migrations on the new schema
automatically (Center.auto_create_schema=True).

## Backup
Per-tenant: `pg_dump --schema=acme starforge > acme.sql`.
Whole DB: standard `pg_dump` / managed-Postgres snapshot.

## Out of scope for v1
- Container orchestration (k8s manifests, Helm charts)
- Observability (Sentry, Prometheus, Grafana)
- Rate-limiting at the edge
- Branch print agent deployment (separate repo)
