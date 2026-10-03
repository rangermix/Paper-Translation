# Full-page DMR parser implementation plan

Status: implementation and offline verification complete.
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
network succeeds. The committed staged snapshot passed 1160 unit cases and 35
focused PostgreSQL cases (1195 total), and six repository checks passed.
These are client/dependency facts, not model inference or ARM evidence. The richer
semantic bridge is covered by the later closure checkpoint.

## 3. Versioned semantic IR and model-output decoding

Add a new schema compatibility version while retaining schema 3.0. Implement the
audit matrix's semantic fields and safe evidence representation. Use model-specific
output contracts over shared rich text/table/layout utilities. Preserve hierarchy,
scientific content, rich cell structure, provenance and explicit roles. Recover
valid elements independently and persist exact response evidence/diagnostics.
Meaningful focused fixtures must cover each matrix row and malformed boundaries.

Implemented: explicit source/render schema 4.0, bounded neutral HTML/CommonMark
semantics, recursive lowering, typed scientific/control content, table/header
relationships and exact per-page receipts. See the [35-row closure matrix](2026-10-02-parser-gap-closure.md).

## 4. Bridge recovery, translation and product consumers

Keep native evidence repair from flattening rich source. Extend source correction,
translation contracts and target validation for new semantics; keep old snapshots
and request limits intact. Register a new reader and support rich semantics in
preview, immutable publication and offline export without editing frozen readers.
Preserve fields in plain-text/search projections where semantic structure cannot
be displayed. Verify round trips and hostile markup/links with real render output.

Implemented: unique semantic reconciliation across recovery/corrections, formatting
restoration and versioned caches, schema-aware API/editor handling, reader-v10 and
both offline export formats. Actual PostgreSQL/worker and browser boundary tests
exercise these contracts without model inference.

## 5. Gap closure and verification checkpoint

Reconcile every independent-audit row against implemented paths and tests, including
legacy compatibility and nonblocking warnings. Run focused unit/API/integration
checks, frontend build/browser checks where affected, repository checks and the
full isolated Docker suite. Cold-start amd64 and arm64 without model downloads.
Record commands, source state, results and limits under a dedicated ignored run
directory; update current docs with source capability and actual evidence.
Review, commit and push only completed checkpoint files. Preserve unrelated work
and do not deploy or clean user instances.

Completed: every G01–G35 row has an implemented disposition and executable evidence
in the [closure matrix](2026-10-02-parser-gap-closure.md). The final frozen Linux/
PostgreSQL suite passed 1916 tests with 18 missing-evidence skips and 29 passing
subtests. Six repository checks, 18 frontend unit tests, 19 project browser tests,
additional rich editor/offline-reader checks, and amd64/arm64 client cold starts
passed. One earlier scheduling-test failure was not reproduced in isolation or
the full rerun; both outcomes are retained in the verification record. Real model
inference and physical ARM/GPU/Metal operation remain unverified. No existing
deployment or unrelated `apps/` files were changed.

## 6. Runtime preparation correction

The deployed Flash parsing job failed before page inference because DMR rejected
the parser's `--default-chat-template-kwargs` startup flag. The cached pinned Flash
and Surya artifacts had already downloaded and imported successfully. Remove that
flag, preserve the existing per-request thinking control, and propagate a safe
configuration-specific failure code. Regression tests replay DMR's rejection for
all four profiles and both backends, and verify failed configuration never writes
a readiness receipt. Redeploy only the verified application client change to the
identified instance; keep its exact model/backend and persistent volumes. Verify
cached preparation separately from any explicitly authorized real PDF inference.

The subsequent real job exposed a second-page `IMMUTABLE_CONFLICT`: the parser
updated a staging evidence index with the immutable-write default. Keep that
fenced staging index atomic and mutable; individual page responses and promoted
source/publication resources remain immutable. Preserve bounded, content-free
failure codes, messages and page/phase/backend context through the child, worker,
API and job detail. Stop on backend execution faults after recording the failed
page evidence; malformed model content remains a nonblocking quality finding.
Show the error before execution logs, including English messages and technical
details. Validate multi-page parsing with injected output, error persistence in
an isolated database, and desktop/mobile rendered job details. Existing failed
jobs may receive an explicitly labeled diagnostic supplement, retaining their
original code and execution outcome. These checks do not certify CUDA inference.
