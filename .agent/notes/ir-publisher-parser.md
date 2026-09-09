# Current continuation

Latest verified state (2026-09-06) is in `notes/parser-source-correction-current.md`; dependency versions below this line are historical where superseded.

# IR / Publisher / Parser implementation handoff

2026-09-06. Agent-owned work area: `packages/ir`, `packages/publisher`, `packages/parsers`, `workers/parser`, focused unit tests. Fixtures and frozen reference CSS were not rewritten.

## Interfaces

- `packages.ir.validate_ir(ir, asset_root=None)` returns the same IR or raises `IRValidationError` with code/path. `validate_source(source, document=None, asset_root=None)` supports parser/worker verification without a translation. Canonicalization rejects duplicate keys through `strict_loads`, nonfinite JSON, and surrogate encoding failures. `digest` accepts bytes or JSON values.
- `Publisher().build(ir, asset_root, output_dir, include_source=False, qa_fingerprint=None)` validates and completes a new directory before rename, never mutates an existing directory, and returns a manifest. Edition pointer CAS is the caller's database responsibility. Pass the actual sealed QA fingerprint; null is never proof of QA approval.
- `verify_artifact(path)` checks listed file lengths and hashes. `export_bundle` and `export_single_html` default to excluding the original PDF, with explicit `include_source=True` requiring the original to already exist in the selected artifact. Exports do not mutate the selected artifact.
- `inspect_pdf(path, limits=None)` runs native PDFium and pypdf validation. Production calls it only inside the isolated parser subprocess. Errors expose stable `PDFError.code` values.
- `DoclingParser.parse(local_pdf, asset_id, output_dir, profile)` requires the exact installed Docling version and all locked local models. No fallback engine, network, OCR, remote services, enrichment, or runtime downloads. Returns `source_revision`, `coverage`, `inspection`, `parser_version`. Source may be null for OCR/no reliable title; `coverage.can_translate` must gate confirmation.
- `packages.parsers.spool.write_request` produces original.pdf then request.json. Result consumers call `verify_result` and recheck current durable fence/control_epoch before content/DB commit. Result status means parser operation finished, not that coverage is publishable.

## Evidence and current limits

Initial tests failed with missing production modules. Focused regressions now pass: 37 tests across IR, publisher, inspector/coverage/spool, including actual native valid/encrypted/disguised PDF and CropBox+90-degree rotation fixtures. `reports/core-evidence/fixture-source-review.json` records source text and locators reviewed against `fixture-original.png` by this implementation agent. A different agent is assigned independent review.

The Docling adapter has not yet completed a real model inference run at this handoff checkpoint. The acceptance agent is building the locked parser image and downloading the two pinned models at build time. Passing adapter/unit tests is not an M1 corpus accuracy claim. Full corpus, real-provider, browser and Docker cold-start results belong in the independent acceptance report.

Native PDF coordinates must pass through PDFium `FPDF_PageToDevice`: simply subtracting y from page height loses text on rotated/cropped pages. This was caught with an actual fixture mutation and fixed; the original fixture remains unchanged.

Source coverage compares independently extracted native text regions against Docling mapped blocks and text characters. Unknown regions fail closed. Decoration exclusion is restricted to page margins. Layout false positives and native text extraction limitations still require the planned corpus/source review. No mechanism silently marks an OCR page complete merely because an image exists.

## Model locking

`deployment/parser-models.lock.json` freezes Docling 2.55.1, layout-old revision b5b4bd59ad2b69aab715e9b1f1dfd74394c45fd4 and docling-models revision fc0f2d45e2218ea24bce5045f58a389aed16dc23. Large-file hashes come from official Hugging Face LFS metadata; small config/README hashes were computed from downloaded bytes. `ops/download_parser_models.py` is build-time only and checks each downloaded file against size and SHA before making it available. The lock is provenance, not a claim that an image or runtime was already tested.

Official API/source references used: https://docling-project.github.io/docling/usage/advanced_options/ ; https://github.com/docling-project/docling/tree/v2.55.1 ; https://pypdfium2.readthedocs.io/en/v4/python_api.html .
