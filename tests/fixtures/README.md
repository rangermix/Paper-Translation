# Authored test fixtures

These inputs exercise automated tests and explicit disposable acceptance harnesses.
They are not application data or parser/model accuracy certificates. Production
images do not include them; runtime schemas and controlled seeds live in
[`res/`](../../res/README.md).

| Corpus | Purpose |
| --- | --- |
| `sample.pdf`, `sample-document.json`, `figure.png` | One-page synthetic PDF and manually authored all-block-type IR used by queue, editor, validator and publisher tests |
| `complex-reader/` | Structured PDF/IR plus an independent visible-text oracle for reader/export checks |
| `cross-page-resources/` | Cross-page parser PDF and expected visible content for the explicit parsing harness |
| `two-column-source/` | Two-column PDF, expected text and its reproducible generator |
| `security/` | Bounded malformed, encrypted, oversized, scanned and inert-action PDFs with a manifest |
| `live-provider/` | Controlled English/Chinese PDFs and a manifest for explicitly authorized model tests |

The authored IR keeps logical `storage_key` values under `fixtures/`; resolve those
assets relative to `tests/` when rendering on the host. Database test setup copies
them into each test's private data root using the same logical keys. This preserves
snapshot content while separating repository resources from stored library paths.

Generators under `.agent/harness/build_*fixtures.py` and
`two-column-source/build_fixture.py` are explicit developer tools. Generation is not
part of application startup. Live-provider fixtures never grant permission to read
real credentials or send content; that runner requires separate authorization.
