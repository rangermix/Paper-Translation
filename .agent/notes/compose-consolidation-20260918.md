# Compose consolidation verification · 2026-09-18

Source checkpoint: `4f955bb7a77ad7d03abafdfa63916e7a9f01909c` on `main`.
This records source/configuration checks and disposable projects, not deployment
or inference acceptance for the existing instance.

## Result

`compose.example.yaml` is the only tracked Compose template. It contains the core
services, commented CPU/CUDA/MLX choices and optional maintenance, local translation,
model export, tests and checks. Seven duplicate Compose inputs and the empty
provider profile/key files were removed. Provider setup uses app Settings and
the managed volume. The ignored local Compose copy retains its instance identity,
image/build choices and parser configuration. No existing service was restarted.

## Checks and environment

Evidence is under `.agent/tmp/compose-consolidation-20260918-pnxjrwie/`.
The verification copy includes this task's files and the committed dependency
manifests; the pre-existing `pyproject.toml`/`uv.lock` edits were preserved and
excluded from the checkpoint and container context. File hashes are recorded in
`verification-manifest.json` and its initial snapshot.

- Docker Compose `5.5.1`; tests/checks built from `tests/Dockerfile` on Linux arm64
  with Python 3.12 and the pinned PostgreSQL test database.
- `docker compose -p paper-compose-tests-pnxjrwie -f compose.example.yaml run --rm tests`:
  **1,248 passed, 18 skipped**, with two dependency deprecation warnings. Skips
  require absent historical parser output or independent review evidence.
- Review found that an internal-only test network suppressed its published port.
  The separate test bridge now supports loopback host access. After this correction,
  **63 focused tests passed** across deployment selection, Compose/harness boundaries,
  provider settings storage and the provider settings API. Container and final
  host repository checks each passed **6/6**.
- CPU, all profiles, CUDA, MLX, MLX with local translation and the preserved local
  configuration passed Compose expansion. Synthetic model IDs were supplied only
  to syntax checks. Eleven harness consumers and the generated restore override
  also passed configuration checks.
- A fresh test project passed host PostgreSQL `SELECT 1`. Cleanup explicitly used
  `--profile tests down --volumes`; unprofiled cleanup had left the optional
  database behind. Final label queries found no containers, networks or volumes
  remaining from any of the three disposable projects.
- A fresh app/database project using the existing app image
  `sha256:f0201c0a7f30314b70498519fc1d2d039f3d1c21ec6ad0188c68f3c01c78d2e2`
  served unconfigured Settings without external files. Synthetic settings saved
  without echoing the key, survived app recreation, and were readable from the
  worker's read-only managed volume. No permits or new jobs were created; the one
  existing migration audit receipt remained unchanged.
- Final review had no unresolved findings. Shell syntax, current Markdown links,
  source-context comparison and `git diff --check` passed. The last two README
  cleanup-command edits were checked separately from the built image.

The full suite preceded the test-network correction; the focused suite and real
host database check cover that final change. The app/database probe intentionally
omitted worker/parser loops, so full readiness reported the missing worker.
No production restart, provider request, model download, hardware inference or
backup/restore exercise was performed.
