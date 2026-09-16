# Docker Compose deployment

Production uses `deployment/compose.production.yaml`; the root Compose file is
the historical prototype. Run these commands from the project root. Only Docker
Engine and Compose are required on the deployment host.

## Single-file CPU / CUDA / MLX example

`compose.example.yaml` contains the full stack with CPU enabled and commented
CUDA and Apple MLX alternatives. Copy it to the repository root as `compose.yaml`
(replacing the bundled prototype configuration in your local copy):

```sh
cp compose.example.yaml compose.yaml
```

Keep exactly one mode block active near the top of the copied file. For CUDA or
MLX, comment out the CPU block and uncomment the complete chosen block, including
the top-level `models` section for MLX. The shared services need no edits.

CUDA needs a compatible NVIDIA GPU, driver, and Docker GPU access. MLX needs
Apple Silicon, Compose 2.38+, Docker Model Runner with a working vLLM Metal
backend, and the packaged Paddle model. Follow
[`deployment/extraction-acceleration.md`](../deployment/extraction-acceleration.md)
to package and verify it, then fill the model ID fields in the copied file or
provide their values in a root `.env` file. Uncommenting MLX does not install or
verify its backend. Hardware modes do not automatically fall back to CPU.

Before upgrading an existing instance, follow the backup/upgrade instructions
below. In particular, a PostgreSQL15-bookworm instance must complete the
fresh-project [backup/restore upgrade](restore.md) before using these images with
its data.

Build and start the selected mode:

```sh
docker compose up --build -d
```

The example uses the same project name and volume names as the production
configuration, so it targets the same library. Keep any existing custom project
name, port, and image/environment overrides when adopting it. This example
configures PDF parsing acceleration; existing optional local translation services
still use `deployment/compose.local-translation.yaml` with the production files.

## Existing deployment script and production files

On macOS/Linux, `./deploy.sh` builds the production images, starts the services,
waits for health checks, and shows their status. Pass your existing Compose
options to keep optional services and configuration, for example:

```sh
./deploy.sh --env-file .agent/local-data/mlx-docker-20260913/mlx.env \
  -f deployment/compose.mlx.yaml -f deployment/compose.local-translation.yaml
```

The script stops if a command fails and preserves existing volumes.

An existing pre-release instance using PostgreSQL15-bookworm must first follow
the fresh-project backup/restore upgrade in `ops/restore.md`. Do not run these
new default startup commands against its original PostgreSQL volume: the base
distribution and libc/collation version changed. The final default is the pinned
PostgreSQL15-trixie base verified with fresh-volume restore. The database image
is built from that fixed base with build-time security updates, always runs as
uid999, and omits the unused root-only `gosu` binary. `DATABASE_IMAGE` can select
an already built immutable database image; offline startup never downloads it.

```powershell
docker compose -f deployment/compose.production.yaml build app parser db
docker compose -f deployment/compose.production.yaml up -d --wait
docker compose -f deployment/compose.production.yaml ps
```

Open `http://127.0.0.1:8080`. There is no registration, account, owner or login.
Setting `PORT` changes the published port and the default allowed localhost/
127.0.0.1 browser origins together. An explicit `APP_ORIGINS` overrides those
derived values when custom hostnames are required.
Every client that can reach this port can modify the library. The default port
binds loopback; no reverse proxy is included. PostgreSQL has no host port. The
separate `deployment/compose.test.yaml` exposes an isolated test database and must
never be merged into production.

Builds fetch dependencies and the pinned Docling models inside Docker. Runtime
containers never install packages or models. The parser has no network and no
database or Provider secret. Missing model assets fail readiness. Use
`docker compose -f deployment/compose.production.yaml logs --tail 100` to inspect
failures; do not paste credentials or document content into reports.

The default Provider profile is `{}` and the mounted key file is empty. The app
can save/read PDFs with no model configuration. Paid processing stays blocked
until a fixed official OpenAI profile, prices and worker-only secret are provided,
then confirmed with a budget for the specific content. Never put the key in the
frontend, PDF parser, source IR, image, URL or command arguments. Versioned profile
changes require renewed authorization. Extra M2 language pairs remain disabled
until their controlled samples have evidence of verification.

Source builds are development candidates until the acceptance report, image
digests, dependency/model hashes, SBOM/licenses, vulnerability report and restore
exercise have all been verified. A successful `config` or image build alone does
not satisfy the release gates. Evidence lives in `.agent/tmp/evidence/`; incomplete gates
remain visible in `.agent/IMPLEMENTATION_STATUS.md`.

Stop without deleting the data:

```powershell
docker compose -f deployment/compose.production.yaml down
```

Do not append `--volumes` to the production stop command: that deletes the library
volumes. A fresh-instance or recovery test must use its own Compose project name.
