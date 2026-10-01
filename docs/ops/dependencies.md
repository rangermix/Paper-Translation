# Dependency evidence

The application and parser use separate images. Their base images are pinned by
registry digest. `uv.lock` pins the Python dependency closure and hashes; the
frontend uses `src/apps/web/package-lock.json`. Runtime images include the built web
bundle, native libraries and per-image Python/system package inventories under
`/app/release/`. A runtime manifest records installed system-package versions;
the final image digest identifies their exact bytes.

`deployment/parser-models.lock.json` and `deployment/parser-vlm-models.lock.json`
are the parser model allowlists. Models are absent from image layers. The separate
`parser-models` service downloads only the selected profile's pinned files on an
explicit Settings preparation request or first parsing use. Downloads are bounded
by byte count, hash checked, written atomically and reused after restart. Interrupted
downloads reuse completed verified files; incomplete files are discarded.
CPU/CUDA parsing uses the read-only cache and an internal preparation network,
without internet access, database credentials or Provider secrets. The lightweight
`runner` image includes no Torch, Paddle, Docling or model weights; Docker Model
Runner owns standard Qwen inference. TeleOCR's custom code is a pinned, hash-checked
local file loaded only on explicit native use. Apple Paddle MLX recognition still
uses the separately packaged, verified Docker Model Runner backend.
TeleOCR's Transformers 4.57 dependencies are locked in `deployment/teleocr/uv.lock`;
its isolated child environment shares the main native Torch packages, so it does
not duplicate Torch wheels or change the other parsers' Transformers 5.17 runtime.
Optional translation weights have their own `src/packages/local_models/models.lock.json`
and are downloaded only on explicit use; settings reads and startup do not prepare
them. See [local translation](../deployment/local-translation.md).

`deployment/images/database.Dockerfile` derives the nonroot PostgreSQL15 runtime from its
fixed trixie base, applies OS updates during build and removes the root-only
privilege-switch helper. Build all three images with `build app parser db`.
Record scanner findings and native linkage limits for the exact built image.
An old scan does not describe a newly built candidate.

PostgreSQL server and the app's `pg_dump`/`pg_restore` clients use major version 15.
Minor versions are recorded by the runtime inventory and verified during backup
tests. Release records must include the actual app/parser/db image IDs and digest,
source commit plus source-tree hash, architecture, all dependency locks, model
manifest, license notices and vulnerability scan results. Unknown or missing
license fields require review; generating an inventory is not legal clearance.
