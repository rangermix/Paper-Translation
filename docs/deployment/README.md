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
any local overrides. All four active parsers use DMR. Set `PARSER_DMR_BACKEND=vllm` or `mlx` and
`PARSER_DMR_URL` for the Docker-managed inference backend. The application image
is shared by API, worker, parser and preparation; Docker supplies a separate
inference engine. See [acceleration](extraction-acceleration.md).

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

The local file contains app, worker, parser, parser-models preparation, database,
initialization and migration services. Optional work uses profiles from the same template:

| Profile | Services and purpose |
| --- | --- |
| `maintenance` | `maintenance`: explicit backup, restore, verification and retention commands |
| `local-translation` | `local-model-init`, `local-translator`: optional Docker Model Runner translation through GGUF/llama.cpp, supported CUDA Safetensors/vLLM, or Apple Silicon MLX |
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
| `images/app.Dockerfile`, `images/database.Dockerfile` | Product image builds |
| `mlx-backend/` | Docker-built macOS MLX payload and extraction helper |
| `local-translation-backend/` | Translation support layered on the same payload |
| `parser-vlm-models.lock.json` | Surya OCR 2, Chandra OCR 2 and Infinity-Parser2 Pro/Flash pinned files |

The shared test/check image recipe is [`tests/Dockerfile`](../../tests/Dockerfile).
Product images exclude test fixtures.

## Configuration and startup

Builds install locked dependencies and contain no parser weights. Runtime containers
never run pip/npm. Settings can explicitly prepare a parser, and first parsing use
prepares it automatically. Only the selected profile's pinned dependencies download
to `parser_models`; startup, settings reads and saving preferences do not download.
The parser mounts that cache read-only. Its downloader has no PDF, DB or credential
mounts. Optional local translation weights are prepared only on explicit use.
For the shared cross-platform Docker Model Runner client,
see [extraction acceleration](extraction-acceleration.md). Declare formats supported by the host with
`LOCAL_TRANSLATION_FORMATS`; a supported engine can appear before installation.
Image inventories and locks are described in
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

The parser has no database or provider secrets. It reaches the internal preparation
service and the provisioned Docker-managed inference backend. See
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
