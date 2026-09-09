# Translation, accounting, legacy and template handoff

Agent `/root/ir_publisher_parser`, 2026-09-06. Workspace memory only; no global memory changes. Root owns the API, editorial policy, database migrations and publication pointer commits. Deployment agent owns current real Docling coverage repairs and independent review. No paid Provider request has been made or authorized.

## Execution contracts

`packages.translation.execution.execute_translation(db,cfg,lease,provider=None)` handles translate/candidate/semantic_review tasks. A planning task creates one durable task per unit; each external request gets a persisted permit and an attempt before transport. A validated late paid response may settle/checkpoint after pause, but never change current content under an invalid fence. Resumption can reuse that checkpoint. Provider failures distinguish not-sent, explicit rejection, unknown outcome and executed invalid output. Unknown reservations remain exposure until reconciliation; no automatic paid replay.

Production uses only `OpenAIResponses` and deployment `PROVIDER_KEY_FILE`; FakeProvider requires explicit test injection. API requests use the fixed official Responses endpoint, `store=false`, no tools, strict output schema, explicit configured model/profile/prompt/price revisions and UTF-8 byte input ceiling. Translation output has exact unit IDs and protected references. Semantic review can emit only evidence issues; it cannot edit text or mark human review.

Candidate jobs bind the draft's `base_glossary_revision` separately from the newly requested glossary revision. They write candidate targets only. Root accepts candidates with per-segment provenance and conditional source/context/version checks, preserving nonselected blocks and reviews. The 100-paragraph regression verified two selected candidates leave all 101 existing segments/review fingerprints unchanged.

`packages.billing.ledger` serializes instance/job budget decisions, limits reserved concurrent dispatches to two, uses integer microcurrency, keeps actual/reserved/unknown totals mutually exclusive, and permits idempotent late settlement. Price snapshots require explicit cached-input rates and output-includes-reasoning; unknown usage dimensions are rejected, never guessed as free.

## Legacy and templates

`packages.seed.legacy.seed_legacy(db,cfg)` is controlled CLI-only seed of exactly two reference-known HTML/PDF/assets. It creates catalog/edition/artifact/publication directly, no synthetic IR/review records. Old bytes remain in legacy-original.html; served index.html applies only the root-approved `../index.html` to `/` navigation correction. Original CSS is unchanged. Artifact manifest carries known inline-script CSP hashes. Export defaults omit original PDFs and navigation; explicit source export preserves source links or embeds PDF bytes. Repeat seed is idempotent and does not resurrect deleted documents.

The new independent reader-v2 CSS extends a byte-identical copy of frozen reader-v1 CSS with focus, narrow screen, overflow and print improvements. New JS uses a separate reader-v2 settings namespace. Registry pins both hashes; publisher selects resources exclusively from that registry and records selected CSS/JS/template/renderer hashes. Editorial `render_input` now derives these from registry. Never edit reader-v1.css to upgrade a template.

`tests/integration/test_template_rebuild.py` builds 20 v1 artifacts and executes 20 durable v2 rebuild jobs through the real worker and PostgreSQL. It checks 40 artifacts, 20 successful generation changes, sealed translation hash equality, unchanged hashes for every old file, zero Provider construction, zero permits and zero cache SQL writes. Its fixtures are copies of the frozen contract sample, not a claim of twenty independently translated real papers.

## Verification pointers

- `reports/core-evidence/template-rebuild-tests.xml`: real PostgreSQL 20-document rebuild regression passed.
- `reports/core-evidence/translation-seed-tests.xml`: earlier 20 focused tests including MockTransport contract, Fake translation checkpoint, billing concurrency and controlled legacy seed passed.
- `reports/core-evidence/core-translation-template-tests.xml`: newest combined regression run.
- `reports/core-evidence/reader-v2-review.md`: separate acceptance agent owns this independent safety/reader review; do not infer its result from implementation tests.

Official OpenAI contract references reviewed: https://developers.openai.com/api/reference/cli/resources/responses/methods/create and https://developers.openai.com/api/docs/guides/structured-outputs . MockTransport tests are not a real Provider acceptance result. Real PDF model accuracy, deployment, browser checks, budgeted online Provider gates remain separately reported by the root and acceptance agents.
