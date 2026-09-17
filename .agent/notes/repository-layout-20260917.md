# Repository layout · 2026-09-17

The user requested a deployment-file inventory, documentation consolidation,
Dockerfile relocation, and a `src/` layout. They explicitly chose a root-level
`res/` directory for runtime resources, separate from documentation.

## Final ownership

| Location | Contents |
| --- | --- |
| `src/apps/` | API and React frontend |
| `src/packages/` | Shared Python code, adjacent package data, migrations and templates |
| `src/workers/` | Background worker and isolated parser |
| `src/tools/` | Repository checks and model download/export/source-generation tools |
| `res/schemas/` | Five serialized-boundary JSON Schemas |
| `res/reference/` | Frozen reader CSS, seed papers/assets and immutable manifests |
| `docs/` | Product baseline, shared contracts, milestones, acceptance planning, operations and deployment prose |
| `deployment/` | Compose definitions, Docker recipes and build/backend/model inputs |
| `tests/`, `fixtures/` | Authored tests and their inputs |

Python module names remain unchanged. Containers use `PYTHONPATH=/app/src`,
pytest uses `src/`, and direct host module commands use `PYTHONPATH=src`.
Production resource loading uses the installed source location, not the shell's
working directory. Frontend commands now use `npm --prefix src/apps/web`.

All 35 former deployment/image files were reviewed: 27 active inputs remain,
six prose files moved into `docs/deployment/`, and two files were consolidated or
removed. The obsolete design-only dependency checklist is gone. Release image
examples from the duplicate environment template now live in root `.env.example`.
The retained CUDA locks, MLX base/translation backends and Compose variants serve
distinct consumers; see `docs/deployment/README.md` for their roles.

Root `compose.yaml` stays ignored. Its only byte changes are the three Dockerfile
path substitutions; canonical configuration comparison also verified all MLX,
model, environment, network, service and volume settings remain unchanged.
No application service was redeployed.

Frozen manifests keep their old logical `reference/` strings, resolved relative
to `res/`. All 55 checked schema, seed/reader and migration files retain their
original bytes. Historical agent notes/evidence remain unchanged; maintained
Python/browser helpers resolve old repository paths without rewriting records.
The Python harness also supports historical images with `/app/packages` as well
as the current `/app/src/packages` layout. No root compatibility symlinks remain.

## Verification

Root evidence directory: `.agent/tmp/repo-layout-20260917-01/`.

| Check | Result | Evidence |
| --- | --- | --- |
| Full Linux/PostgreSQL suite | 1,216 passed; 18 historical-evidence skips | `pytest-full.log` |
| Final harness/layout regressions | 42 passed in the final test image | `final-harness-container-tests.log` |
| Browser suite | 133 passed; 27 live/historical opt-in skips | `browser-full.log` |
| Frontend unit tests and build | 18 passed; production bundle built | `frontend-unit.log`, `frontend-build.log` |
| Repository/schema/frozen-content/link checks | 50 passed | `package-final.log` |
| Compose static resolution | All 10 configurations passed | `compose-final.json` |
| Immutable content | 55 files unchanged | `immutable-resource-check.json` |
| Source/config binding and syntax | 422 image files match; 320 Python, 49 JSON, 3 TOML parse | `final-static-and-image-binding.json` |
| App image on Linux/arm64 | Built; isolated HTTP/resources smoke passed | `app-build.log`, `app-smoke.log` |
| App image on configured Linux/amd64 | Built; isolated HTTP/resources smoke passed | `app-amd64-build.log`, `app-amd64-smoke.log` |

The full suite preceded the final two historical-image topology regression cases;
the 42-test final run includes those cases. Its count is not added to the full-suite
number. The test container uses Linux/arm64 on this Mac and a dedicated PostgreSQL
container; exact host/Docker/image details are in `environment.json`. App smoke
checks run as UID 10001 with no network or production volumes and verify HTTP
liveness, built frontend delivery, capabilities, two seeds, three templates and
13 migrations. They do not replace a full production cold start.

Independent reviews covered backend resource/subprocess paths, all seven Docker
recipes (47 direct repository COPY inputs), and frontend/browser import paths.
Their evidence is under `.agent/tmp/repo-layout-20260917-backend/`,
`.agent/tmp/repo-layout-20260917-deployment/`, and
`.agent/tmp/repo-layout-20260917-frontend/`.

No model download/inference, parser/CUDA/MLX image rebuild, real Provider call,
credential access or production deployment was performed. Dependency versions,
model locks, publication artifacts and migration checksums were not changed.

## Checkpoints

- `678ce23`: documentation and Docker build-input organization, verified and pushed.
- The subsequent source/resource relocation commit contains this note; resolve its
  exact ID from this file's Git history.
