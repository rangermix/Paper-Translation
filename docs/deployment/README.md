# Docker Compose deployment

Run from the repository root. [`compose.example.yaml`](../../compose.example.yaml)
is the only tracked Compose template. For a new instance, copy it to ignored local
`compose.yaml`, select the desired parser configuration, and build:

```sh
cp compose.example.yaml compose.yaml
docker compose build app parser db
docker compose up -d --wait
docker compose ps
```

Keep an existing local file and its project name, image pins, hardware settings and
any local overrides. The template enables CPU parsing. To select CUDA or MLX, edit
the copied file: comment the CPU mode block and uncomment the chosen mode block,
including its required model declaration for MLX. Keep exactly one mode active.
Compose does not choose hardware automatically. See [acceleration](extraction-acceleration.md).

The optional helper runs the same build, startup and status sequence using the
existing local `compose.yaml`; it exits if that file is missing:

```sh
./deploy.sh
```

Open `http://127.0.0.1:8080`. `PORT` sets the published port and default browser
origins. `BIND_ADDRESS`, `ALLOWED_HOSTS` and `APP_ORIGINS` configure deliberate
nondefault exposure; there is no login or reverse proxy. Only the app publishes
a port in the normal product stack. Stop with the same Compose configuration and
`down`, without `--volumes`.

## Services and optional profiles

The local file contains app, worker, parser, database, initialization and migration
services. Optional work uses profiles from the same template:

| Profile | Services and purpose |
| --- | --- |
| `maintenance` | `maintenance`: explicit backup, restore, verification and retention commands |
| `local-translation` | `local-model-init`, `local-translator`: optional Docker-managed MLX translation |
| `model-tools` | `model-export`: export already packaged parser weights to an explicitly mounted directory |
| `tests` | `tests`, `test-db`: disposable Linux/PostgreSQL regression suite |
| `checks` | `checks`: repository checks with no network, dependencies or product volumes |

Use `docker compose run ... SERVICE` for one-off tools. For local translation,
enable its profile as described in [local translation](local-translation.md).
Tests and checks use an explicit separate project and `-f compose.example.yaml`;
follow [tests/README.md](../../tests/README.md). Do not use an unqualified profile
`up` command to run tests: it also starts the default product services.

## Build inputs in deployment

| Input | Purpose |
| --- | --- |
| `images/app.Dockerfile`, `images/parser.Dockerfile`, `images/database.Dockerfile` | Product image builds |
| `cuda/`, `cuda-paddle/` | Separate locked environments for incompatible native dependencies |
| `mlx-backend/` | Docker-built macOS MLX payload and extraction helper |
| `local-translation-backend/` | Translation support layered on the same payload |
| `parser-models.lock.json` | Parser weight revisions, sizes and SHA-256 allowlist |

The shared test/check image recipe is [`tests/Dockerfile`](../../tests/Dockerfile).
Product images exclude test fixtures.

## Configuration and startup

Builds install locked dependencies and package parser weights. Runtime containers
never run pip/npm or fetch parser weights. Optional local translation weights are
prepared only on explicit use. Image inventories and locks are described in
[dependencies](../ops/dependencies.md).

The complete default stack starts without a translation profile or key.
`/health/ready` still requires the worker and parser to be running with fresh
heartbeats, alongside its database and storage checks. In Settings, save the
service endpoint, protocol, model and optional credential, then confirm the
content/destination for a job. New instances allow model requests without a
separate enable switch; each connection test and translation still requires
confirmation. Existing dispatch pauses are preserved and show a recovery action
in Settings. Saving settings makes no
inference request. Settings and keys persist in the managed `provider_config`
volume; no provider profile or key bind files are needed. Preserve that volume
when updating. Dispatch pauses do not disable DOI metadata lookup or explicit
model preparation.

Default CPU/CUDA parser processes have no network, database or provider secrets.
MLX parsing reaches the provisioned Docker-managed backend. See
[acceleration](extraction-acceleration.md), [MLX setup](mlx-backend.md) and
[local translation](local-translation.md).

## Updating an instance

Record the selected project/configuration and running images, then create and
verify a backup before changing them. Use [backup and restore](../ops/restore.md)
for schema, database-base or host changes. Merge required service/profile definitions
from the current template into an older local copy while retaining its volume names,
project identity and hardware settings. Remove retired external provider profile/key
bindings after configuring the provider through the app; retain the managed
`provider_config` volume. App, worker and maintenance must use compatible source
and schema; migrations are additive and checksum protected.
Check `/health/ready`, worker/parser health and the actual selected model after
an update. A successful build or `docker compose config` does not prove model
inference or a complete recovery exercise.
