# Docker Compose deployment

Run from the repository root. For a new instance, copy `compose.example.yaml` to
ignored local `compose.yaml`, select the desired parser configuration, and build:

```sh
cp compose.example.yaml compose.yaml
docker compose build app parser db
docker compose up -d --wait
docker compose ps
```

Keep an existing local file and its project name, image pins and overlays. The
shared composable entry point is `deployment/compose.production.yaml`; its default
parser is CPU. Use it explicitly when that is your chosen deployment:

```sh
docker compose -f deployment/compose.production.yaml build app parser db
docker compose -f deployment/compose.production.yaml up -d --wait
```

Open `http://127.0.0.1:8080`. `PORT` sets the published port and default browser
origins. `BIND_ADDRESS`, `ALLOWED_HOSTS` and `APP_ORIGINS` configure deliberate
nondefault exposure; there is no login or reverse proxy. Only the app publishes
a port. Stop with the same Compose configuration and `down`, without `--volumes`.

## Inputs that remain in deployment

| Input | Purpose |
| --- | --- |
| `compose.production.yaml` | App, worker, parser, database, init, migration and maintenance services |
| `compose.cuda.yaml` | CUDA parser image selection and GPU access |
| `compose.mlx.yaml` | Docker Model Runner binding and parser inference network |
| `compose.local-translation.yaml` | Optional local translation sidecar and cache |
| `compose.model-package.yaml` | Export locked parser weights for Docker model packaging |
| `images/app.Dockerfile`, `images/parser.Dockerfile`, `images/database.Dockerfile` | Product image builds |
| `cuda/`, `cuda-paddle/` | Separate locked environments for incompatible native dependencies |
| `mlx-backend/` | Docker-built macOS MLX payload and extraction helper |
| `local-translation-backend/` | Translation support layered on the same payload |
| `parser-models.lock.json` | Parser weight revisions, sizes and SHA-256 allowlist |
| `provider-profile.json`, `provider_key.empty` | Empty compatibility inputs explicitly bound by Compose; allow unconfigured startup |

The two empty provider files are intentional mount targets, not credentials.
Managed settings supersede the external compatibility profile once saved.
Test-only Compose files and their shared image live under [`tests/`](../../tests/README.md).
Product images exclude test fixtures. Repository checks use that test image and
have no network, database dependency or product volumes.

## Configuration and startup

Builds install locked dependencies and package parser weights. Runtime containers
never run pip/npm or fetch parser weights. Optional local translation weights are
prepared only on explicit use. Image inventories and locks are described in
[dependencies](../ops/dependencies.md).

The library starts without a translation profile or key. In Settings, save the
service endpoint, protocol, model and optional credential, enable translation
dispatch, and confirm the content/destination for a job. Saving settings makes no
inference request. The dispatch switch does not disable DOI metadata lookup or
explicit model preparation.

Default CPU/CUDA parser processes have no network, database or provider secrets.
MLX parsing reaches the provisioned Docker-managed backend. See
[acceleration](extraction-acceleration.md), [MLX setup](mlx-backend.md) and
[local translation](local-translation.md).

## Updating an instance

Record the selected project/configuration and running images, then create and
verify a backup before changing them. Use [backup and restore](../ops/restore.md)
for schema, database-base or host changes. App, worker and maintenance must use
compatible source and schema; migrations are additive and checksum protected.
Check `/health/ready`, worker/parser health and the actual selected model after
an update. A successful build or `docker compose config` does not prove model
inference or a complete recovery exercise.
