# Dependency evidence

API, worker, parser and preparation share one image. Base images are pinned by
registry digest. `uv.lock` pins the Python dependency closure and hashes; the
frontend uses `src/apps/web/package-lock.json`. Runtime images include the built web
bundle, native libraries and per-image Python/system package inventories under
`/app/release/`. A runtime manifest records installed system-package versions;
the final image digest identifies their exact bytes.

`deployment/parser-vlm-models.lock.json` is the active parser model allowlist.
Models are absent from image layers. The separate `parser-models` service downloads
only the selected profile's pinned files on explicit preparation or first use.
Downloads are bounded by byte count, hash checked, written atomically and reused
after restart. Completed verified files survive an interrupted download. The
application image includes no Torch, Transformers, Paddle, Docling or ONNX runtime;
Docker Model Runner supplies inference for the four full-page parsers. The parser
mounts its cache read-only and has no database or translation credentials.
Archived parsers/dependency locks are excluded from image inputs.
Optional translation weights have their own `src/packages/local_models/models.lock.json`
and are downloaded only on explicit use; settings reads and startup do not prepare
them. See [local translation](../deployment/local-translation.md).

`deployment/images/database.Dockerfile` derives the nonroot PostgreSQL15 runtime from its
fixed trixie base, applies OS updates during build and removes the root-only
privilege-switch helper. Build both product images with `build app parser db`.
Record scanner findings and native linkage limits for the exact built image.
An old scan does not describe a newly built candidate.

PostgreSQL server and the app's `pg_dump`/`pg_restore` clients use major version 15.
Minor versions are recorded by the runtime inventory and verified during backup
tests. Release records must include the actual app/parser/db image IDs and digest,
source commit plus source-tree hash, architecture, all dependency locks, model
manifest, license notices and vulnerability scan results. Unknown or missing
license fields require review; generating an inventory is not legal clearance.
