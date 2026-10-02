# Full-page DMR parsing and information preservation

Status: implemented and verified offline; real model/hardware inference not run.
Completed evidence: [gap closure and verification](2026-10-02-parser-gap-closure.md).
Source baseline: `47c01be9b8c752db3d4cde89c388d57cb73aa790`.

## Requested outcome

Only Surya OCR 2, Chandra OCR 2 and Infinity-Parser2 Pro/Flash are executable parser
options. All four process full pages through Docker Model Runner. Docling Standard
and Granite inference are removed. PaddleOCR-VL, Xiaomi and TeleOCR source is
archived outside runtime source/build inputs for possible future restoration.
Existing stored parser identities and saved results remain readable; removing a
parser must never rewrite an installed migration, queued task snapshot, sealed
source/translation revision or published resource.

Surya OCR 2 is the default for new preferences because it has the smallest
locked model. This is a resource choice, not an OCR-quality ranking. Saved inactive
choices are reported as inactive and require a new explicit selection for new
parses; no job silently switches its model or backend.

## Boundaries

- One small project application image supports amd64/arm64. API, worker, parser and
  preparation remain separate Compose services with their existing data/credential
  boundaries. PostgreSQL and Docker's inference backend have their own images.
- No Torch, Transformers, Paddle, Docling, ONNX inference framework, CUDA runtime,
  model weights or archive sources are bundled in the application image.
- Parser weights remain pinned by revision, byte count and SHA-256 and prepare only
  on explicit preparation/use. Startup and settings reads/writes never download.
- DMR backend, effective configuration, artifact identity and response model remain
  verified. Portable client images do not certify backend architecture/hardware
  support. No host inference service replaces Docker Model Runner.
- Original PDFs, literal model responses and independently extracted PDF evidence
  remain separate from decoded semantic content. Generated markup is never served
  as executable HTML. Quality findings remain nonblocking.
- New information contracts receive new compatibility identifiers; the existing
  schema 3.0 and reader resources remain available without in-place modification.

## Useful-information acceptance contract

The independent audit supplies a complete gap matrix before implementation. Each
useful field must have a tested disposition: semantic IR, original-image evidence,
bounded parser annotations with provenance, or preserved raw response plus an
explicit diagnostic when interpretation is unsupported. Merely retaining an
opaque response is insufficient for a semantic field the product can use.

The bridge covers printed text and boundaries; reading order and nested structure;
heading depth; lists and list nesting/markers; code text/whitespace/language;
inline and display math; superscript/subscript; emphasis and links; figures and
captions; tables including rich cells, header roles and spans; references and
footnotes; coordinates and coordinate conventions; useful confidence/role/source
annotations; raw evidence and decoding/truncation diagnostics. Source content or
geometry absent from a response is not invented. Unknown fields are preserved as
bounded evidence rather than silently discarded.

One malformed element must not discard valid neighboring elements. Partial results
retain order, original evidence and specific warnings. Incomplete output is never
misrepresented as a complete page. Decoder/model-contract versions participate in
the parser fingerprint so new behavior cannot be attributed to old snapshots.

Semantic preservation must continue through source correction, translation input
and target validation, reader rendering, search/plain-text projections and offline
export. Nontranslatable/protected scientific notation stays protected; keeping
formatting must not grant generated HTML, URLs or model annotations executable
authority. Mechanical PDF-evidence corrections retain or explicitly reconcile
existing rich text and provenance without silently flattening it.

## Compatibility

### Chosen representation

The [independent audit](2026-10-02-parser-gap-audit.md) defines G01–G35 and the
T1–T12 validation groups. Its documented model/SDK pins are the contract authority;
the implementation does not import those SDKs or their inference dependencies.

Source snapshots from the new parser carry `schema_version: 4.0`; render inputs
also use 4.0. An absent source version means the unchanged historical 3.0 contract.
The successor schema is a separate resource, never a replacement for 3.0.

- A neutral intermediate layout retains semantic trees, rich inline runs, original
  roles and output paths before native recovery. Recovery operates once per real
  outer layout region; reconstruction reconciles changed text against preserved
  runs. Protected spans cannot be silently overwritten or attached to stale text.
- Existing semantic blocks and protected atoms remain the main representation.
  New `group` containers and recursive ownership represent compound layout, lists,
  list continuations and structured content inside table cells. Heading parentage
  retains its existing meaning. Both ownership and heading graphs are acyclic.
- Expanded allowlisted marks retain underline, deletion and scripts. Static form
  controls are protected typed values with state; they never become active inputs.
  Inline math is typed LaTeX without invented delimiters. Code preserves whitespace.
- Table cells retain explicit header roles, scopes/associations and row groups.
  Formula captions and scoped figure/table/page notes receive explicit relationships.
  Ambiguous relationships stay separate, with an evidence diagnostic.
- Provenance records whether a region is emitted, inherited or independently
  recovered, plus the source output path. Nested HTML debug coordinates are retained
  as evidence, rather than treated as separately contracted block geometry. It does
  not invent finer coordinates,
  polygons or confidence. All selected raw models use 0–1000 rectangles.
- Bounded per-page inference envelopes persist exact response content before
  decoding, completion state, usage and verifiable model/backend identity. Unknown
  labels and derived visual/chemical descriptions stay inert evidence with warnings.
  Unsupported or damaged siblings do not erase valid source leaves.
- `reader-v10` and a separate renderer support the successor language. Legacy
  template rendering remains on the existing renderer; published bytes and exports
  remain immutable. Newly parsed source selects a compatible reader by default.
- Translation uses a bounded formatting restoration protocol that preserves span
  associations through unit splitting and text-only local translators. Text edits
  retain marks; source corrections reconcile marks and recursive relationships.

Each audit row must be reconciled to implemented paths and meaningful tests before
this implementation is recorded as complete. Missing model output is a documented
capability limit, not a field the decoder can restore.

New source IR is explicitly versioned and has a registered reader for all new
semantics. Old schemas, source snapshots and readers stay accepted. New API inputs
accept only active parser profiles; historical records may retain retired IDs.
Queued retired/native jobs fail with an actionable unavailable-parser result,
without changing their frozen choice or content history. There is no production
deployment or mutable local Compose update in this source checkpoint.

## Verification and delivery

Use model-authoritative output examples and authored boundary cases for every gap.
Validate syntax, IR semantics, protected content, actual decoded values, persistence
and reader/export behavior, not tests that only echo the implementation. Include
partial/malformed/truncated output, unsafe links/markup, coordinate variants,
multi-column/nested layouts, scientific notation, rich tables and immutable legacy
fixtures. Run focused checks first, then the repository's isolated Docker test and
check services and frontend checks. Cold-start both client architectures without
weights or inference frameworks.

Real trained-model inference and host GPU/Metal support are separate evidence.
Record any unverified runtime/quality limits honestly. Commit and push verified
checkpoints to the configured branch without unrelated `apps/` files.

See the [implementation plan](2026-10-02-dmr-parser-plan.md).
