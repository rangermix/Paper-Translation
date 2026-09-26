# Translation Consistency Implementation Plan

**Delivery status (2026-09-27):** the six source checkpoints below are implemented.
The separate local analyst is MiniCPM5-1B Q4 through the existing MLX/DMR service.
External retrieval, additional models, embeddings and hierarchy remain the extension
gates at the end of this plan. Production deployment and real-model quality/runtime
acceptance are separate from the source/test delivery.

> **For the implementing agent:** Use `superpowers:executing-plans` for a separate
> execution session, or `superpowers:subagent-driven-development` in this session.

**Goal:** Give local and API translation a frozen, source-grounded paper brief
and scoped terminology, with optional model preparation and advisory checks.

**Architecture:** Add pure preparation modules to the existing fenced translation
job flow. Reuse existing JSON snapshots, provider binding, accounting, draft
provenance and glossary UI; preserve source units and immutable publications.

**Tech Stack:** Python, FastAPI/Pydantic, PostgreSQL/SQLAlchemy, existing provider
HTTP adapters and Docker Model Runner; React/TypeScript frontend; pytest and
Playwright. No new inference framework or embedding dependency for the default.

---

The [specification](2026-09-26-translation-consistency-design.md) is the acceptance
contract. The [catalogue](translation-consistency-options.md) records alternatives
without claiming all are implemented. Execute the following checkpoints with
meaningful failing tests first, focused green checks, review, then commit/push
only the verified files. Preserve pre-existing `pyproject.toml`/`uv.lock` edits.

## 1. Pure source preparation

Create `src/packages/preparation/{__init__,collection,terms,context}.py` and
`tests/unit/test_preparation.py`.

1. Add independently authored blocks containing an abstract, contributions,
   section definitions, repeated terms, two senses of `rank`, references and
   protected notation. Assert exact evidence, deterministic hashes, bounded
   selection, original-only exclusion and source immutability.
2. Run the focused tests and verify the missing-feature failure.
3. Implement source collection, conservative language-aware term/acronym rules,
   frequency ranking, scoped concepts and an extractive brief. Preserve rare
   defined concepts even when the frequency threshold is not met.
4. Implement projection of applicable explicit glossary entries and automatic
   proposals. Existing choices win; unrelated terms are omitted; ambiguity does
   not become a global mandatory replacement.
5. Run tests, inspect fixture results, and commit/push the verified module.

Representative contract assertions:

```python
pack = collect(source)
assert source == before
assert all(e['quote'] in blocks[e['block_id']]['normalized_text']
           for e in pack['evidence'])
assert pack['source_hash'] == digest(source)
assert collect(source) == pack
```

## 2. Durable freeze and translation integration

Modify `src/packages/translation/{execution,planner,languages,pipeline}.py`,
`src/apps/api/{workflow,continuation,candidates}.py` and
`src/packages/editorial/drafts.py`. Add focused tests in
`tests/integration/test_translation_preparation.py` and extend
`tests/unit/test_translation.py`.

1. Add failing integration tests for preparation at the shared planning hook,
   legacy jobs without options, changed source/glossary identity and frozen
   snapshots reused across units.
2. Add strictly validated per-job `off`, `extractive`, `provider`, `local` choices. New forms
   default to extractive; existing frozen jobs keep legacy behavior.
3. Freeze preparation before fan-out under existing lease/source locks. Store
   the digest and bounded pack in job/draft JSON; derived profile fields cannot
   alter provider identity.
4. Select per-unit context and terms, include them in cache identity and record
   them in segment provenance. Preserve provenance in edits, continuation and
   candidate acceptance. Keep current protected-source normalization intact.
5. Add a read-only draft preparation endpoint, validating ownership/tombstones.
6. Verify pause/cancel, source replacement, deletion, retry and maintenance
   fences. Do not introduce a migration unless a new relational invariant
   actually requires one; never modify installed migrations.
7. Review and commit/push this complete deterministic flow.

## 3. Bounded optional model preparation

Create `src/packages/preparation/{analysis,execution}.py`; modify
`src/packages/providers/{contract,registry,openai_responses,gemini_interactions,claude_messages,local_translation}.py`
and translation execution/checkpoint integration as needed. Add
`tests/unit/test_preparation_providers.py` and preparation integration cases.

1. Write response-contract tests: unknown concepts/evidence, unsupported claims,
   empty or excessive output, same term in two scopes, conflicts with explicit
   glossary, and unreviewed provenance.
2. Add one bounded structured analysis request for capable API models. Keep
   protocol/destination/model fixed. Integrate a separate pinned small local
   analyst through `src/packages/local_models/{catalog,service}.py`,
   `src/packages/local_models/models.lock.json`, and a new
   `src/packages/providers/local_analysis.py`. Keep its role separate from the
   translation selector and test the native template, response normalization,
   model identity, download lifecycle and owned-model memory scheduling.
3. Use a durable task per request with existing authorize/settle/unknown handling.
   Bind the selected analyst profile separately from the translation profile in
   permit validation, task history and estimates. Budget every call, including reasoning/output caps; never dispatch within a
   planning transaction. Save a validated checkpoint before applying results.
4. On validated semantic-output rejection, retain extractive preparation and
   record a warning. Do not hide actual execution/budget/configuration errors.
5. Freeze final proposals before creating translation units; allow no automatic
   overwrite of existing glossary entries and no fake human review.
6. Test replay after interruption, stale controls, unknown outcome, model
   mismatch, settled malformed-output fallback and deletion after dispatch.
   Do not add a paid content-repair retry for optional preparation.
7. Review and commit/push the optional flow.

## 4. Model-native context and advisory QA

Modify `src/packages/providers/local_translation.py`, shared API instructions,
`src/packages/editorial/drafts.py` and related provider/QA tests.

1. Add regressions showing that background is separate from source output, a
   context-pack change invalidates the cache, and old local jobs omit neighbors.
2. Pack within actual request bounds, removing optional context before source.
   Keep exact protected markers and output unit ownership. Use native supported
   background templates; adapters without support use relevant terms only.
3. Evaluate current unit terms in deterministic QA. Findings include applicable
   concept/evidence and remain nonblocking. Unresolved ambiguity is not failure.
4. Verify source-only retention, candidates, number/citation checks, sealing and
   publishing are unchanged. Review and commit/push.

## 5. User controls and inspectable results

Create `src/apps/web/src/features/translation-preparation.tsx`. Modify
`src/apps/web/src/{types,messages}.ts` and translation/upload/editor feature files.
Add `tests/browser/translation-preparation.spec.ts` and relevant API tests.

1. Show a shared preparation selector in upload, parse-confirmation, edition,
   continuation and candidate flows. Explain extra requests and local capability
   without requiring approval of content quality.
2. Ensure changing the mode invalidates a previously checked consent when it
   changes processing scope. Submit the mode with the existing profile and
   source identity. Preserve optional budget semantics.
3. Show the frozen brief, source quotes, scoped terms, generated/unresolved status
   and a route to existing glossary editing. Separate draft baseline, selected
   segment and candidate evidence. Reading never dispatches inference.
4. Update progress presentation and conservative preflight estimates to account
   for optional preparation. Unknown money remains null.
5. Verify rendered desktop/mobile interactions and request payloads with
   Playwright; run frontend unit/type/build checks; review and commit/push.

## 6. Regression, documentation and handoff

Update `docs/{architecture,workflows,api,product-baseline}.md`,
`docs/deployment/local-translation.md` and `tests/README.md` to describe only
implemented behavior. Keep this plan's status accurate; remove superseded claims.

Run focused tests during implementation. For final reproducible checks, use an
explicit disposable project and available loopback test port, for example:

```sh
TEST_DB_PORT=55449 docker compose -p paper-consistency-tests -f compose.example.yaml run --build --rm tests
docker compose -p paper-consistency-checks -f compose.example.yaml run --build --rm checks
npm --prefix src/apps/web test
npm --prefix src/apps/web run build
```

Browser procedure and evidence directories follow
[the browser guide](../../tests/browser/README.md). Test-container build uses
locked dependencies and requires no runtime provider keys. Do not use the ignored
production Compose file, start all profiles, or delete production volumes.

Record fresh results and skipped evidence boundaries. Independently review spec
compliance and code quality, address findings, commit/push verified checkpoints,
then verify remote branch identity and preservation of unrelated changes.

Real inference is a separate acceptance run requiring an explicit content and
budget authorization. Compare the same PDFs/locales across off/extractive/model
modes and measure downstream terminology/sense accuracy, omissions, cold/warm
latency, memory and token usage. Mock success cannot certify model quality or
local hardware compatibility. No deployment is implicit in source completion.

## Extension gates

External abstract/TLDR connectors require exact identity/version comparison,
deduplication and explicit network preferences. Additional local analyst candidates
require pinned model artefacts, Docker Model Runner support and model-specific
evaluation. Embeddings, terminology databases, larger chunks, hierarchical
analysis and training are independent options, not hidden prerequisites for the
working default. Revisit these gates with measured baseline failures.
