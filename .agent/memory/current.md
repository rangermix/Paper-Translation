# Current source handoff · 2026-09-17

This describes the checkout, not a live instance. Inspect the selected deployment
before runtime claims or service changes. Work from the repository root and commit
and push completed, verified checkpoints to the configured branch/remote.

## Maintained structure

- `src/`: app, domain packages, workers and tools. Host Python module calls use
  `PYTHONPATH=src`; pytest and containers configure it already.
- `res/`: the runtime render-input schema and frozen reader/controlled seed assets.
  Their persisted format/template identities remain compatible.
- `tests/`: regression code, authored fixtures, shared test/check Dockerfile and
  Compose definitions. Test corpora are absent from production images.
- `deployment/`: production Compose, hardware/local-model overlays, product recipes,
  backend payload sources, locked models/dependencies and required empty config inputs.
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

`compose.example.yaml` is the shared standalone template. Root `compose.yaml` and
machine editor settings are ignored local files. Preserve their project name,
image pins, model settings and overlays. `deployment/compose.production.yaml` is
the shared composable entry point.

## Verification and evidence

Use [tests/README.md](../../tests/README.md) and current docs. `tests/compose.yaml`
provides isolated repository checks and a Linux/PostgreSQL suite. The optional
[harness](../harness/README.md) captures source-bound execution/review evidence;
it does not maintain a retired milestone-completion catalog.

Test doubles, static checks and historical hardware/model runs have limited scopes.
Real API keys require explicit test budget and content-egress authorization.
Existing dated notes describe only their recorded commit/environment. No cleanup
operation here is production deployment or new inference proof.

The [2026-09-17 cleanup verification](../notes/repository-current-cleanup-20260917.md)
records commit `331a642`, the full regression results, app-image checks and deliberate
compatibility exceptions. It is a dated source record, not a live-instance status.

Use unique `.agent/tmp/` run directories. `.agent/local-data/` is persistent private
state and never disposable scratch. Both are ignored; `.agent/` is excluded from
product images. Keep archived evidence unchanged; known path moves resolve through
`.agent/relocation.json`. Deleted plans remain available in Git history.
