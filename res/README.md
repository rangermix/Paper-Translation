# Runtime resources

Only application inputs belong here. Synthetic PDF/IR corpora are
[test fixtures](../tests/fixtures/README.md) and are excluded from product images.

| Path | Runtime consumer |
| --- | --- |
| `schemas/document-ir.schema.json` | `packages.ir.validator`: render-input syntax, alongside semantic validation |
| `reference/reader-v1.css` | Frozen reader template registered by `packages.templates` |
| `reference/legacy-manifest.json` | `packages.seed.legacy`: controlled seed allowlist and navigation patch |
| `reference/reference-files.sha256.json` | Byte-integrity verification of frozen reader/seed inputs |
| `reference/legacy/` | Two seed HTML readers, their original PDFs and every referenced figure |

The optional `python -m packages.maintenance seed-legacy` command imports exactly
the reviewed, hash-listed seed papers into the selected instance. This is a
maintenance operation, not a general HTML/IR import endpoint. It does not run on
normal startup. These readers are supplied reference material, not exact extraction
or translation-quality gold; production translation starts from the PDFs.

Manifest paths beginning `reference/` are resolved relative to this `res/` directory.
Keep their content hashes and the supplied HTML/PDF/CSS/image bytes unchanged.
Schema and reader identifiers are persisted format/template revisions, independent
of the project's package version. API request and model-output schemas are defined
by their actual Python validators rather than duplicate JSON copies here.
