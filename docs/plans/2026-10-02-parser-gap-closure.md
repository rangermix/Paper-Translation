# Full-page DMR parser gap closure

Status: all 35 audited gaps have implemented dispositions; offline verification complete.
Authority: [specification](2026-10-02-dmr-parser-spec.md),
[implementation plan](2026-10-02-dmr-parser-plan.md), and the independently
executed [Astra/max audit](2026-10-02-parser-gap-audit.md). The audit describes the
baseline before implementation; this document records the resulting disposition.

## Active architecture

Surya OCR 2, Chandra OCR 2 and Infinity-Parser2 Pro/Flash are the four active
full-page parsers. All use DMR. Docling/Granite inference is removed. Paddle,
Xiaomi and TeleOCR are preserved in [the archive](https://github.com/rangermix/Paper-Translation/tree/main/archive/parsers),
outside runtime/build inputs. New preferences default to Surya for model size;
saved retired choices remain visible and require explicit replacement. Recorded
retired/native jobs fail with their original identity, without reassignment.

API, worker, parser and preparation share the same application image. It contains
HTTP clients, PDF inspection/rasterization/recovery and semantic conversion, but
no model weights or native inference frameworks. Separate Docker inference
backends still have their own platform/hardware dependencies. Locked weights
download into the model cache on explicit preparation/use, with SHA-256 checks.
Startup and ordinary settings reads/writes do not prepare models.

## Implementation and tests

The shared [semantic decoder](../../src/packages/parsers/semantic.py) and
[model contracts](../../src/packages/parsers/vlm_output.py) construct neutral
semantic trees before the [source adapter](../../src/packages/parsers/source_adapter.py).
[Rich reconstruction](../../src/packages/parsers/rich_ir.py) preserves typed
content across PDF recovery and lowers it into the separate
[4.0 schema](../../res/schemas/document-ir-v4.schema.json).
[Translation planning](../../src/packages/translation/planner.py) and
[the new reader](../../src/packages/publisher/rich_renderer.py) preserve meaning
through consumers. Historical 3.0 validation/rendering remains separate.

Test aliases below link to actual executable authored fixtures:

- **S:** [parser semantics](../../tests/unit/test_parser_semantics.py).
- **B:** [boundaries and native evidence](../../tests/unit/test_semantic_boundaries.py).
- **C:** [translation, correction and reader consumers](../../tests/unit/test_semantic_consumers.py).
- **I:** [real PostgreSQL/API/worker workflows](../../tests/integration/test_semantic_pipeline.py).
- **L:** existing compatibility, parser runtime, recovery and publication tests in
  [the test tree](../../tests/README.md), including `test_vlm_parser.py`,
  `test_parser_profiles.py`, `test_parser_fidelity.py`,
  `test_table_source_adapter.py` and the historical-reader suites.

These fixtures use authored PDFs/model outputs and offline inference/provider
doubles. They verify contracts and lifecycle behavior, not trained-model quality.

| Gap | Implemented disposition | Evidence |
| --- | --- | --- |
| G01 | Recursive semantic leaves/groups preserve boundaries and order without duplicate container prose. | S compound blocks; C recursive order; I split/merge. |
| G02 | Explicit inline math becomes a protected typed literal; display math remains a separate block without synthetic delimiters. | S math/scripts; B nested equation captions; C planner and reader. |
| G03 | Literal math/code is isolated before HTML repair. Unclosed literal regions retain original imagery and a specific warning. | S inequality payload; B unclosed math and valid neighbors. |
| G04 | Sub/sup, deletion and underline marks retain identity. Protected static controls retain state, value and select options without active inputs. | S marks/controls; B static controls; C target validation; browser edit/reader checks. |
| G05 | Allowlisted marks survive source construction, bounded translation units, restoration, cache, editing and rendering. | S styles; C splitting/cache; I durable provider validation and API publication. |
| G06 | Inline code is protected. Block code preserves indentation/newlines and bounded language metadata. | S compound code; B nested pre/code; browser exact code text check. |
| G07 | Safe external destinations and labels remain separate; unique explicit internal targets resolve to xrefs. Unsafe destinations retain the visible label and diagnostic. | B RTL/unsafe links/notes; C translated labels/cache; I edits and exports. |
| G08 | CommonMark AST decoding applies to documented Infinity text categories; formula and HTML table payloads use their own contracts. | S bare-array Markdown/truncated siblings; B qualified JSON table paths; L four-profile route cases. |
| G09 | Explicit heading ranks take precedence over numeric fallback. Navigation title fallback retains its warning rather than becoming confirmed metadata. | S explicit fourth-level heading; L heading/title and recovery cases. |
| G10 | Recursive list ownership retains item boundaries, nesting, continuation, starts, reversed/value semantics and marker style. | S nested lists; B list/control boundaries; reader DOM/screenshot checks. |
| G11 | Shared typed inline/cell trees preserve math, code, scripts, links, empty cells and captions in valid grids. Invalid grids use explicit original-image fallback. | S rich table; B column groups/static content; L span/fallback grids; I publication/export. |
| G12 | Explicit th roles, scope, headers and row/column groups are validated and rendered with matching HTML semantics. | S header relationships; B column groups; C DOM; I offline exports; browser th/headers checks. |
| G13 | Table-cell owners can contain paragraphs, lists and tables. Child locators inherit the real enclosing rectangle when no finer geometry is emitted. | S compound cells and inherited scope; B rotated crop proof; I owned paragraph split/merge. |
| G14 | Caption/note subtype survives. Nested relationships remain explicit; separate typed regions associate only with a unique same-page geometric owner. | B formula/table/figure scoped relationships and nested captions; C note DOM. |
| G15 | Bibliography entries retain explicit boundaries; scripts and proven note fragments retain target identity. Reader citation resolution preserves styled labels. | B internal anchors/bibliography; C canonical note anchors; L reference/citation suites; browser navigation. |
| G16 | Derived visual/chemical descriptions are labeled inert annotations, with original pixels. Printed nested captions remain source, including after graphic recovery. | S figure/chemistry; B nested caption and graphic-transcription preservation. |
| G17 | Special roles map explicitly to list/form/TOC/complex groups or graphics. Unknown roles preserve text/raw identity with a diagnostic; hr remains a typed separator. | S unknown-role case; B long roles, separators and controls; decoder contract mappings. |
| G18 | Non-margin header/footer content is retained with a warning. Proven page-margin furniture can still be excluded using PDF evidence. | Source adapter branch; L fidelity/margin coverage cases. |
| G19 | Output identity, record/DOM/literal paths and geometry scope survive. JSON table paths identify the decoded text field; literal offsets are Unicode code points. Nested debug boxes stay auxiliary. | S geometry invariants; B JSON path qualification, rotated crops and receipt hashes. |
| G20 | Semantic trees travel through native recovery. Exact span slicing and joins preserve associated runs; uncertain reconciliation has an explicit warning and preserved evidence. | S repair/protected invariants; B reference slicing and graphic transcription; L recovery; I source edits. |
| G21 | Formatting/link boundaries define plain-text units with deterministic restoration. Bindings enter cache identity; provider responses cannot invent formatting or destinations. | C splitting/cache/local transport; I real queue/provider schema/reassembly checkpoints. |
| G22 | Schema-aware API validation and frontend editing support every inline kind and preserve fields on edits. Protected values remain protected. | C invalid marks; I CAS/hostile edit; browser field-by-field PATCH preservation. |
| G23 | Unicode offsets, indivisible atoms and unique reconciliation preserve corrections. Recursive ownership order, adjacent owned splits/merges and retargeting remain validated. | C corrections/cycles; I real owned paragraph split/merge; L source revision cases. |
| G24 | reader-v10 typesets unwrapped typed math using the pinned offline runtime and preserves invalid-literal text fallback/original comparison. | C math DOM/export; browser actual KaTeX rendering in offline HTML. |
| G25 | Independent malformed elements do not erase valid siblings. Explicit blank pages are accepted and checked against available PDF evidence. | S bad/blank/unknown neighbors; B duplicate JSON keys; L coordinate rejection. |
| G26 | Completion state and usage are retained before decoding. Complete JSON prefix entries can be recovered; damaged HTML/unfinished literals have diagnostics. | S durable truncation; B refusal/unusable completions and partial cases. |
| G27 | Exact bounded page envelopes and manifest receipts are written atomically before decoding; verified source paths are rebased during fenced worker promotion. | B raw corruption rejection; I real spool promotion; L parser progress/fences and deletion races. |
| G28 | Adapter `full-page-dmr-v3-semantic`, decoder `full-page-semantic-v2`, source normalization `semantic-native-v2` and planner `semantic-abbreviation-units-v8` distinguish new processing. The planner preserves source-defined abbreviation spellings. Decoder v2 preserves horizontal separators as layout groups inside captions, notes and references. Prompt/contract pins, preprocessing and actual artifact/backend identity enter receipts/fingerprints. Engine version remains null when unverifiable. | S receipt identity; B contract pin/hash; L backend/config/model mismatch and progress history. |
| G29 | The neutral SourceAdapter and source helpers import no retired inference framework. Active selection and historical identity reading are distinct. | L dependency imports, profile/spool retirement and settings tests; image cold imports. |
| G30 | Separate schema/renderer/reader-v10 supports publication and both offline exports. Historical artifacts/resources/migrations remain untouched. | C new/old template compatibility; I immutable source/sealed hashes, publish and exports; L historical-reader suites. |
| G31 | No SDK wrapper polygon, block probability or confidence is fabricated. Unknown engine metadata remains unknown; supplied raw metadata retains its original scope. | B no polygon/confidence and exact receipts; L model progress identity. |
| G32 | HTTP/response, table slots, depth/nodes, block/text/atom, annotation, receipt and image limits are bounded. Repetition is a nonblocking warning. Oversized interpretation uses an original-image fallback with exact response evidence. | B loop/depth/capacity/repetition and long metadata; L memory/spool bounds. |
| G33 | Existing inline projections expose typed literal values and labels. Empty containers and auxiliary narratives add no duplicate/source text to search or preparation. | S flatten equality; C source/target projections; I actual search index; L preparation tests. |
| G34 | Code converted into a figure retains exact indentation in an original-only `code_transcription` annotation, alongside the crop and caption. Graphic text transcriptions remain explicitly auxiliary. | B code-as-figure and nested printed caption cases; L code recovery cases; reader escaped evidence. |
| G35 | Appendix equation labels such as (A.1) are retained only with exact native same-baseline evidence; mismatches remain independent. Emitted TeX tags remain literal. | B positive/negative native equation proof; S protected math; L equation layout tests. |

## Capability and preservation limits

The raw full-page contracts provide normalized rectangles, not independently
measured child-cell/glyph coordinates, polygons or calibrated block confidence.
Inherited geometry is deliberately coarse. Raw generated chart/diagram/SMILES
interpretations are inspectable auxiliary evidence, not printed source or a human
review claim. Semantic fields missing from model output cannot be reconstructed
without independent PDF evidence.

HTML decoding uses safe semantic markup rather than arbitrary CSS/scripts. Infinity
text uses CommonMark; formula payloads remain exact LaTeX and table HTML remains a
separate bounded tree. Literal offsets identify the stripped decoder input for
HTML, or the decoded JSON text field for JSON tables; DOM paths identify the
repaired semantic tree, not original-byte offsets. Full original responses remain
available in receipt files. Longer metadata/annotations have bounded projections
and explicit diagnostics; full values remain in receipts within response limits.

Ambiguous source repairs/relationships are not guessed. Code/math is indivisible;
translations split at formatting boundaries, which can reduce linguistic context
despite preserving association. Actual OCR completeness, language fluency, DMR
architecture support and GPU/Metal operation require separate model inference
evidence. No real model weights or credentials were accessed, no PDF content was
sent to real inference, and no existing deployment was changed.

## Verification record

The earlier runtime checkpoint `9634343` passed 1160 unit cases plus 35 focused
PostgreSQL cases from its staged source snapshot (1195 total), and six repository
checks. Its amd64 application image reported 428,598,147 bytes. Those results apply
to that checkpoint, before the richer semantic implementation.

Focused semantic/PDF tests, real PostgreSQL API/CAS/seal/publish/export/search,
receipt promotion and durable fake-provider translation pass. Frontend unit tests
passed 18 cases. The project browser suite passed 19 parser-settings/review/navigation
cases. Additional authored browser checks preserved all edited rich inline fields
at 1440 and 390 pixels. The exported rich reader rendered three actual KaTeX
expressions, nested lists/cells, header associations, exact code whitespace and
canonical note navigation at both widths, with no console errors, external requests
or page overflow while offline. Screenshots were visually inspected.

The final product/test inputs were frozen from staged Git tree
`863317fcadece29b3ecd2aaad8d5eb9049c7dade`, with source-tree SHA-256
`bf99472f64f1e832fc5d0eea5712aba3ef08b55ec4ccd4008f985142940ac44d`.
Only final verification documentation was edited afterward; product/test inputs
remain unchanged.
The locked Linux test image builds the frontend and runs against the isolated
`paper-dmr-ir-20261002-it` PostgreSQL project, with a 4 GiB container limit.
Six repository checks passed on the frozen image. They include static Compose and
Markdown integrity; they do not constitute production deployment or model inference.

The final suite passed **1916 tests, with 18 skips and 29 passing subtests**, in
234.41 seconds. Skips require missing recorded parser inference or independent
original-page review, and are not acceptance passes. The full command used the
frozen image override:

```sh
docker compose -p paper-dmr-ir-20261002-it \
  -f compose.example.yaml \
  -f .agent/tmp/dmr-parser-ir-20261002/complete.compose.yaml \
  run --rm tests python -m pytest -q -rs -p no:cacheprovider
```

An earlier run of the same frozen source reported 1915 passes and one failure in
`test_local_analyst_has_separate_frozen_billing_profile`: its second queue claim
returned no lease. The case passed in isolation. The full rerun above added a
read-only, failure-only queue diagnostic plugin from the run directory
(`-p preparation_probe`); it passed all 1916 cases without suppressing or changing
the test. The intermittent failure's cause was not reproduced or established.
The initial, isolated and full-rerun logs are retained separately. No scheduling
workaround or product retry was added to hide the result.

Both final application images were built with `docker buildx build --platform
linux/amd64` or `linux/arm64 --load`, using that frozen context and its recorded
`SOURCE_TREE_SHA256`. The local probe images identify their revision as
`uncommitted`, reflecting the staged snapshot used for the build. They were not
published or deployed. Docker reported these sizes after unpacking and startup:

| Architecture | Local image ID | Size in bytes |
| --- | --- | --- |
| amd64 | `sha256:659ff46a35259586922cbf08e3338673bba46835c1f55edcc74957db4c8a95ee` | 428,823,297 |
| arm64 | `sha256:f1ae0463ecf8340b386ab6f3750dfab718350c1d6346b47cffa93a7ccb27f205` | 477,029,302 |

Both ran the actual parser one-shot heartbeat and application HTTP liveness/frontend
checks with a read-only filesystem, no network, 1 GiB memory limit and empty model
cache. They expose all four profiles and ten registered readers. Torch, Transformers,
Paddle, Docling, ONNX Runtime and OpenCV modules, bundled model weights and archive
sources are absent. The arm64 process ran under Docker's emulation on this amd64
host; this is client startup evidence, not a physical ARM/GPU/Metal inference test.
The probe deliberately used an unreachable dummy database URL, so its HTTP checks
establish liveness and bundled frontend availability rather than database readiness.

Run evidence is under ignored `.agent/tmp/dmr-parser-ir-20261002/`, including logs,
JSON reports, reader artifacts and screenshots. `full-suite-complete-recheck.log`
is the final suite, `checks-complete.log` records frozen-image checks,
`checks-delivery.log` records checks with only final documentation overlaid, and
`cold-amd64-complete.log` / `cold-arm64-complete.log` record startup probes.
Intermediate mutable source-bind runs are diagnostic only; they do not certify
the final checkpoint.
