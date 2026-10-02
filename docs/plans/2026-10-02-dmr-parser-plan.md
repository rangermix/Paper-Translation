# Full-page DMR parser implementation plan

Status: implementation in progress; independent contract audit completed.
Acceptance authority: [specification](2026-10-02-dmr-parser-spec.md).

## 1. Independent contract audit and completed specification

The separately dispatched Astra agent at maximum reasoning independently reads
the four pinned model contracts, decoders, schema, recovery and consumers. Convert
its findings into a tracked gap matrix with proposed representation and tests.
Resolve compatibility and useful-information dispositions before runtime edits.

Completed: [Astra/max audit](2026-10-02-parser-gap-audit.md), 35 gap rows and 12
validation groups. The specification records schema 4.0, recursive neutral
semantics, durable inference evidence and a new reader as the chosen bridge.

## 2. DMR-only catalog and portable shared application image

Archive Paddle/Xiaomi/TeleOCR implementation, manifests and restoration notes
outside runtime inputs. Remove Docling/Granite inference and native dependency
groups/build flavors. Rename/extract the model-free result adapter and retain its
PDF fidelity/recovery logic. Keep historical parser identity reading separate from
active profile validation; do not reassign old jobs or saved choices. Update API,
settings, parser environment, preparation, Compose, deployment and current docs.
Use the application image for API, workers, parser and preparation with distinct
commands, networks and mounts. Verify removed frameworks and weights are absent.

Checkpoint: shared application image built on amd64 (428,598,147 bytes reported
by Docker); no native inference modules are installed and cold import with no
network succeeds. Offline unit checks passed (1161 cases), focused PostgreSQL
selection/runtime checks passed (93 cases), and six repository checks passed.
These are client/dependency facts, not model inference or ARM evidence. The richer
semantic bridge below remains in progress.

## 3. Versioned semantic IR and model-output decoding

Add a new schema compatibility version while retaining schema 3.0. Implement the
audit matrix's semantic fields and safe evidence representation. Use model-specific
output contracts over shared rich text/table/layout utilities. Preserve hierarchy,
scientific content, rich cell structure, provenance and explicit roles. Recover
valid elements independently and persist exact response evidence/diagnostics.
Meaningful focused fixtures must cover each matrix row and malformed boundaries.

## 4. Bridge recovery, translation and product consumers

Keep native evidence repair from flattening rich source. Extend source correction,
translation contracts and target validation for new semantics; keep old snapshots
and request limits intact. Register a new reader and support rich semantics in
preview, immutable publication and offline export without editing frozen readers.
Preserve fields in plain-text/search projections where semantic structure cannot
be displayed. Verify round trips and hostile markup/links with real render output.

## 5. Gap closure and verification checkpoint

Reconcile every independent-audit row against implemented paths and tests, including
legacy compatibility and nonblocking warnings. Run focused unit/API/integration
checks, frontend build/browser checks where affected, repository checks and the
full isolated Docker suite. Cold-start amd64 and arm64 without model downloads.
Record commands, source state, results and limits under a dedicated ignored run
directory; update current docs with source capability and actual evidence.
Review, commit and push only completed checkpoint files. Preserve unrelated work
and do not deploy or clean user instances.
