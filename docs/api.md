# API guide

The running FastAPI application exposes its generated schema at `/openapi.json`
and interactive documentation at `/docs`. Request models and routes in
[`src/apps/api/`](../src/apps/api/) are authoritative; internal runtime models live
in [`src/packages/`](../src/packages/). Separate hand-written API schema copies
are not maintained.

Most routes use `/api/v1`. Reader/artifact file routes use `/read/` and `/artifacts/`.
There are no account, login, workspace or IR-upload endpoints.

## Requests and concurrency

Write requests require `X-Library-Request: 1` and an accepted Origin when present.
Host/Origin checks are not authentication. JSON models reject undeclared fields.
Creation/action routes use `Idempotency-Key`; mutable resources additionally use
`If-Match` with the returned ETag. Missing preconditions return 428, stale versions
412 and business conflicts 409. Consult each generated operation for its body.

Errors contain `error.code`, `message`, `retryable`, optional resource/details and
`request_id`. Submitted secrets and exception stacks are not returned. Time fields
are UTC; monetary amounts use integer micro-units or `null` when unknown.

`GET/PATCH /settings/preferences` includes `upload_translation_profile_hash`.
It defaults to `null`. Supplying the current ready provider's hash explicitly
enables the upload form's saved translation permission; sending `null` clears it,
and omitting the field preserves it. Updates require the current settings ETag.
Uploads still submit their own `workflow.external_processing_confirmed` and
`profile_hash`, binding each queued request to its source and destination. When
using this default, the form also sends `workflow.use_saved_upload_permission`.
Import rechecks the stored permission under a settings lock, so an already-open
tab cannot reuse a revoked default. This flag only permits extractive preparation.

| Route group | Implementation and behavior |
| --- | --- |
| `/uploads`, `/imports`, `/documents` | [library.py](../src/apps/api/library.py): chunked PDF intake, metadata, original files and parsing |
| `/imports/{id}/preflight`, `/editions/{id}/translate` | [workflow.py](../src/apps/api/workflow.py): source/profile-bound translation confirmation |
| `/drafts/{id}/translation-preflight`, `/drafts/{id}/translate` | [continuation.py](../src/apps/api/continuation.py): continue from a saved source/draft |
| `/jobs`, `/jobs/{id}/logs`, `/jobs/{id}/recovery` | [workflow.py](../src/apps/api/workflow.py): progress, paginated logs, recovery and task controls |
| `/jobs/history`, `/jobs/history/clear` | Eligible main-task count and visibility-only clearing of completed tasks and their internal steps with explicit confirmation |
| `/drafts`, `/candidates`, `/sources` | [editorial.py](../src/apps/api/editorial.py), [candidates.py](../src/apps/api/candidates.py), [sources.py](../src/apps/api/sources.py): edits, review and source revision operations |
| `/templates`, `/editions`, `/artifacts`, `/exports` | [catalog.py](../src/apps/api/catalog.py), [artifacts.py](../src/apps/api/artifacts.py): template selection, publication, history and downloads |
| `/settings/provider`, `/settings/local-models` | [provider_settings.py](../src/apps/api/provider_settings.py): saved profiles, explicit tests and local model preparation |
| `/settings/preferences`, `/settings/parser-environment`, `/settings/parser-models`, `/settings/parser-models/prepare`, `/settings/dispatch` | [catalog.py](../src/apps/api/catalog.py): preferences, Compose-owned parser capabilities, model preparation and dispatch state; preferences do not accept a device override |
| `/glossaries`, `/translation-memory`, `/search`, `/reading-position` | [knowledge.py](../src/apps/api/knowledge.py) and [catalog.py](../src/apps/api/catalog.py) |

Quality findings are descriptive and nonblocking. Confirmation bodies still bind
the source/profile hash, destination authorization and current generation; stale
confirmations cannot authorize a different model or document. Keys are write-only
settings inputs. Listing capabilities or reading settings does not call providers
or download local models.

Local translation profiles accept `local_backend` (`llama.cpp`, `vllm`, or `mlx`)
only when compatible with the pinned model. New saves record an explicit backend;
legacy profiles retain their default without rewriting immutable revisions.
`GET /settings/local-models` exposes `inference_backends`, `default_backend` and
per-engine `backend_states` independently of installation/readiness.
`POST /settings/local-models/{id}/prepare?backend=ENGINE` prepares the exact
selected engine and rejects unsupported model/deployment combinations. The
backend participates in the command's idempotency payload and task snapshots.

`/health/live` reports HTTP liveness. `/health/ready` checks the database schema,
storage integrity, bundled templates, frontend and current worker/parser heartbeats.
A liveness response alone does not establish readiness or successful inference.

## Task presentation

The [task model](task-model.md) defines task kinds and relationships.
`/jobs?top_level_only=true` returns main operations, including automatically
started parsing, translation and publication. `operation` is the user-facing
kind; `stage` remains the stored execution stage. `task_role` is `main` or `step`.

Existing `parent_job_id` values retain both kinds of relationship. Query
`/jobs?parent_job_id=ID&relationship=internal` for contained steps, or
`relationship=related` for separate follow-up main tasks. Both lists paginate;
`include_cleared=true` keeps historical links navigable. Omitting `relationship`
preserves the existing all-children API behavior. The default `/jobs` still
exposes raw execution records for existing clients.

`workflow.status` and `workflow.job_count` summarize only the selected operation
and its internal job records, excluding separate follow-up operations. Status
and model/stage filters on the main-task list consider internal work too. The
stored `status`, progress, execution times, model and costs retain their original
scope for details and versioned controls. History preview/clear counts are main
tasks; an operation is clearable only when it and all its internal steps have
finished without leased work or unsettled requests.

## Paper preparation

Upload workflow options, import confirmation, edition translation, draft continuation
and candidate creation accept `preparation: {"mode": "extractive"}`. Modes are `off`,
`extractive` (the default for new requests), `provider` and `local`. Persisted jobs
without preparation options retain the legacy behavior. `provider` requires an API translator;
`local` freezes a separate pinned analyst and works with either translator type.
Semantic review is independent and does not run preparation.

Translation preflight returns `preparation_estimates` by mode, with
`additional_requests`, `additional_cost_micro` and `backend`. The analysis request
bound excludes repeated translation context. Unknown money is `null`; extractive/off
add zero requests. These are bounds, not measured inference costs.

`GET /drafts/{id}/preparation` returns `{available, preparation, scope, context_modes}`.
Its default scope is the draft baseline. Supply `block_id` for the current segment's
original preparation, or `candidate_id` for a candidate belonging to the draft;
the parameters are mutually exclusive. An unprepared segment returns no pack even
when the draft has one. Packs bind exact source revision/hash, locale, evidence,
concepts, glossary, algorithm versions and optional analyst identity. The endpoint
does not invoke models or download weights.

`GET /settings/local-models?purpose=analysis` lists pinned analysts separately
from the default translation catalogue. `GET /settings/preferences` includes
`local_analyst_model_id` (the pinned artifact identity) and `local_analyst_backend`.
Save both using `PATCH /settings/preferences` with the current `If-Match`; only
analysis models and compatible deployment backends are accepted. This does not
change the translation provider, download weights or invoke a model. Local
preparation snapshots these settings when a new task is created.
The existing explicit `POST /settings/local-models/{id}/prepare?backend=ENGINE`
prepares either type. Reading status never starts downloads.
Job `progress` includes `preparation_status`, `preparation_requests`,
`preparation_terms` (proposed equivalents), `preparation_warnings`,
`preparation_context_mode` and `preparation_omitted_units`.

## Upload metadata

Native PDF inspection queues an independent `metadata_lookup` job before the full
parse. The worker queries Crossref first by DOI, with DOI Citation Formatter as a
fallback for identifiers not available there. Without a selected DOI, it searches
Crossref using the PDF's embedded title/author or a prominent first-page heading.
Filename-like and missing titles are skipped. Only the DOI or bounded title/author
fields leave the instance; the metadata lookup sends no PDF, body text or provider
credentials. Native parsing only contacts its internal model preparation service;
DMR/MLX inference sends page images to the local Docker-managed backend.

A standalone arXiv stamp before the first-page body, or a complete dated vertical
stamp in either side margin of that page, supplies the preprint's
[arXiv-assigned DOI](https://info.arxiv.org/help/doi.html). Margin detection checks
the stamp's shape and position even when it starts below the abstract heading.
Version suffixes do not change that DOI. An explicit DOI in metadata or the first-page header takes
precedence; conflicting stamps remain ambiguous. Body citations and reference
lists are not arXiv identity evidence.
The preprint uses the same Crossref-first lookup and DOI fallback, retaining paper
matching checks instead of substituting a later conference publication.

Title searches inspect up to five results and require an exact normalized title.
An available author hint must corroborate a full author name, allowing initials;
without authors, only distinctive titles can match. Multiple matching DOIs remain
ambiguous. Crossref ranking alone never selects a paper. Matching metadata includes
title, authors, publication date/year, journal or proceedings, publisher and DOI.

`GET /uploads/{id}` exposes `metadata_status`, `bibliography` and the latest
`doi_discovery`, allowing the upload page to show results without waiting to import.
Metadata arriving before import is applied when the document is created; later
results update its catalog entry unless the user has renamed it. Missing or
unverified results and lookup failures preserve the upload and filename. Immutable
source revisions and published resources are unchanged.

Requests have bounded time and response size; temporary failures and rate limits
receive at most three background attempts. Verified results are cached by DOI.
`POST /documents/{id}/metadata/refresh` retries a lookup or accepts an explicit
`doi`; it re-inspects old, unselected discovery evidence when necessary. Reuploading
the same PDF can also refresh old discovery evidence while retaining selected DOIs.

Endpoint and query behavior follow the [Crossref REST API guidance](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/).
