# Current implementation handoff · 2026-09-17

This is a source handoff, not a statement about a live instance. Check the actual selected deployment before making runtime claims or changing its services. Work from the Git repository root, using the configured branch and remote; commit and push verified checkpoints. Preserve unrelated work and local configuration.

## Current source

- The repository uses `src/` for executable code, `docs/` for prose/plans, root `res/` for runtime schemas and frozen assets, and `deployment/` for Compose/Docker inputs. Docker recipes are under `deployment/images/`.
- Product code is in `src/apps/`, `src/packages/`, and `src/workers/`. Schema migrations currently end at 13; old migration checksums and published artifacts remain immutable.
- The retired demonstration app, prototype server and generated design pages were removed in `fdf8a61`. The two controlled seed papers are under `res/reference/legacy/`; `res/reference/reader-v1.css` remains frozen.
- Nonblocking content quality, automatic recovery, DOI metadata, optional costs, all languages, task history clearing, original-only scholarly metadata and optional local translation are implemented. The current contract is `docs/product-baseline.md` plus the relevant `docs/shared/` and deployment documents.
- PaddleOCR-VL-1.6 is the new parsing default; Docling and Granite remain available. CPU/CUDA assets are packaged. MLX uses Docker Model Runner and requires deployment-specific proof. Local translation models are prepared only on explicit use, never by startup or settings reads.
- `compose.example.yaml` is the shared standalone template; root `compose.yaml` is local and ignored. `deployment/compose.production.yaml` remains the maintained composable entry point. Keep the active project's name, overrides and image bindings when doing maintenance. Machine-specific `.vscode/settings.json` is also local.

## Verification and limits

- `tests/README.md` describes reproducible database, memory-bounded Linux and browser tests; `deployment/compose.verify.yaml` runs portable repository checks independently of local hardware configuration.
- `.agent/IMPLEMENTATION_STATUS.md` links to historical full-milestone evidence. Later targeted tests and historical hardware/model runs do not certify the current tree as a full release.
- No real API key may be read or used for testing without explicit budget and content-egress authorization. FakeProvider, local HTTP doubles and static Compose checks have narrower proof scopes.
- The 2026-09-17 directory layout and verification are recorded in `.agent/notes/repository-layout-20260917.md`; its run artifacts are under `.agent/tmp/repo-layout-20260917-01/`.
- Repository audit results and current verification commands are recorded in `.agent/notes/repository-audit-20260916.md`; its run artifacts are under `.agent/tmp/repo-audit-20260916-01/`.

## Preserved history and local data

The [previous handoff](../notes/handoff-before-repository-audit-20260916.md) is unchanged historical context. Its Windows paths, old image IDs, open-work claims and “uncommitted” labels are not current instructions. Dated notes under `.agent/notes/` describe their recorded source/environment only.

Use a unique `.agent/tmp/` directory for each run. `.agent/local-data/` contains persistent environments, receipts and private state and must never be cleaned as scratch. Neither directory is tracked or shipped in images. Resolve legacy relative evidence paths with `.agent/relocation.json`; do not rewrite archived evidence or run old instance-mutating scripts without checking their target.
