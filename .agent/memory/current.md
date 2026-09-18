# Current source handoff · 2026-09-18

This describes the checkout, not a live instance. Inspect the selected deployment
before runtime claims or service changes. Work from the repository root and commit
and push completed, verified checkpoints to the configured branch/remote.

## Maintained structure

- `src/`: app, domain packages, workers and tools. Host Python module calls use
  `PYTHONPATH=src`; pytest and containers configure it already.
- `res/`: the runtime render-input schema and frozen reader/controlled seed assets.
  Their persisted format/template identities remain compatible.
- `tests/`: regression code, authored fixtures and the shared test/check Dockerfile.
  Test corpora are absent from production images.
- `deployment/`: product image recipes, backend payload sources and locked
  models/dependencies. Compose services are consolidated in the root template.
- `docs/`: current product, architecture, workflow, API and operations guides.
  Completed plans, duplicate schemas and obsolete milestone registries were removed.

## Implemented behavior

The app implements PDF intake, parsing/recovery, translation continuation, optional
editing/review, nonblocking content findings, original-only scholarly metadata,
DOI metadata, task logs/history visibility, immutable publication/export and maintenance.
Database migrations end at 13 and installed migration bytes remain frozen.

New parser preferences default to PaddleOCR-VL-1.6. Docling/Granite and saved choices
remain available. MLX uses Docker Model Runner with deployment-specific verification.
Local translation models prepare only on explicit use; startup/settings reads do
not download them. Source-only results are not translated results.

`compose.example.yaml` is the only tracked Compose template. CPU is the default;
choose CUDA/MLX by editing the commented mode blocks in the local copy. It also
contains `maintenance`, `local-translation`, `model-tools`, `tests` and `checks`
profiles. Root `compose.yaml` and machine editor settings are ignored local files.
Preserve the instance's project name, image pins, model settings and local overrides.
`deploy.sh` requires that local file; it does not fall back to a production template.
Provider configuration and keys are saved through app settings in the existing
managed `provider_config` volume, without provider profile/key bind files.

## Verification and evidence

Use [tests/README.md](../../tests/README.md) and current docs. Run the template's
`checks`/`tests` services with explicit separate projects and `-f compose.example.yaml`.
The test service depends only on `test-db`; `TEST_DB_PORT` defaults to 55439.
Do not use profile-wide `up` for tests, which also starts default product services.
The optional [harness](../harness/README.md) captures source-bound execution/review evidence;
it does not maintain a retired milestone-completion catalog.
Disposable offline probes generate their overrides inside unique run directories.

Test doubles, static checks and historical hardware/model runs have limited scopes.
Real API keys require explicit test budget and content-egress authorization.
Existing dated notes describe only their recorded commit/environment. No cleanup
operation here is production deployment or new inference proof.

The [2026-09-17 cleanup verification](../notes/repository-current-cleanup-20260917.md)
records commit `331a642`, the full regression results, app-image checks and deliberate
compatibility exceptions. It is a dated source record, not a live-instance status.

The [2026-09-18 Compose verification](../notes/compose-consolidation-20260918.md)
records `4f955bb`: 1,248 regression passes and 18 historical-evidence skips, followed
by 63 focused passes after the test-network correction. App-managed settings
save/reload and host test-database access passed on disposable projects. Test
cleanup requires `--profile tests down --volumes` with its explicit separate project.
The existing instance was not restarted and model inference was not exercised.

Use unique `.agent/tmp/` run directories. `.agent/local-data/` is persistent private
state and never disposable scratch. Both are ignored; `.agent/` is excluded from
product images. Keep archived evidence unchanged; known path moves resolve through
`.agent/relocation.json`. Deleted plans remain available in Git history.
