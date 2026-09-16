# Dependency evidence

The application and parser use separate images. Their base images are pinned by
registry digest. `uv.lock` pins the Python dependency closure and hashes; the
frontend uses `apps/web/package-lock.json`. Runtime images include the built web
bundle, native libraries and per-image Python/system package inventories under
`/app/release/`. A runtime manifest records installed system-package versions;
the final image digest identifies their exact bytes.

`deployment/parser-models.lock.json` is the parser model allowlist. Model downloads
occur during image build through `ops/download_parser_models.py`. Enabled layout
table, OCR, formula/code and VLM models must match every declared byte count and
hash. CPU/CUDA parsing uses fixed local assets without network access. Apple MLX
recognition uses the separately packaged, verified Docker Model Runner backend.
Optional translation weights have their own `packages/local_models/models.lock.json`
and are downloaded only on explicit use; settings reads and startup do not prepare
them. See [local translation](../deployment/local-translation.md).

`images/database.Dockerfile` derives the nonroot PostgreSQL15 runtime from its
fixed trixie base, applies OS updates during build and removes the root-only
privilege-switch helper. Build all three images with `build app parser db`.
Do not substitute a successful vulnerability scan for a complete review:
`.agent/tmp/evidence/release/DEPENDENCY_TRIAGE.md` records remaining scanner findings and
native linkage limitations for the exact candidate images.

PostgreSQL server and the app's `pg_dump`/`pg_restore` clients use major version 15.
Minor versions are recorded by the runtime inventory and verified during backup
tests. Release records must include the actual app/parser/db image IDs and digest,
source commit plus source-tree hash, architecture, all dependency locks, model
manifest, license notices and vulnerability scan results. Unknown or missing
license fields require review; generating an inventory is not legal clearance.

The original `dependency-inventory.json` remains a historical responsibility
checklist. Null versions/hashes in that file never count as a release lock. The
harness refuses to mark missing runtime/Compose/provider proof as passed.
