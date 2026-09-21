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

| Route group | Implementation and behavior |
| --- | --- |
| `/uploads`, `/imports`, `/documents` | [library.py](../src/apps/api/library.py): chunked PDF intake, metadata, original files and parsing |
| `/imports/{id}/preflight`, `/editions/{id}/translate` | [workflow.py](../src/apps/api/workflow.py): source/profile-bound translation confirmation |
| `/drafts/{id}/translation-preflight`, `/drafts/{id}/translate` | [continuation.py](../src/apps/api/continuation.py): continue from a saved source/draft |
| `/jobs`, `/jobs/{id}/logs`, `/jobs/{id}/recovery` | [workflow.py](../src/apps/api/workflow.py): progress, paginated logs, recovery and task controls |
| `/jobs/history`, `/jobs/history/clear` | Global eligible count and visibility-only clearing with explicit confirmation |
| `/drafts`, `/candidates`, `/sources` | [editorial.py](../src/apps/api/editorial.py), [candidates.py](../src/apps/api/candidates.py), [sources.py](../src/apps/api/sources.py): edits, review and source revision operations |
| `/templates`, `/editions`, `/artifacts`, `/exports` | [catalog.py](../src/apps/api/catalog.py), [artifacts.py](../src/apps/api/artifacts.py): template selection, publication, history and downloads |
| `/settings/provider`, `/settings/local-models` | [provider_settings.py](../src/apps/api/provider_settings.py): saved profiles, explicit tests and local model preparation |
| `/settings/preferences`, `/settings/parser-environment`, `/settings/dispatch` | [catalog.py](../src/apps/api/catalog.py): current preferences, Compose-owned parser device/capabilities and dispatch state; preferences do not accept a device override |
| `/glossaries`, `/translation-memory`, `/search`, `/reading-position` | [knowledge.py](../src/apps/api/knowledge.py) and [catalog.py](../src/apps/api/catalog.py) |

Quality findings are descriptive and nonblocking. Confirmation bodies still bind
the source/profile hash, destination authorization and current generation; stale
confirmations cannot authorize a different model or document. Keys are write-only
settings inputs. Listing capabilities or reading settings does not call providers
or download local models.

`/health/live` reports HTTP liveness. `/health/ready` checks the database schema,
storage integrity, bundled templates, frontend and current worker/parser heartbeats.
A liveness response alone does not establish readiness or successful inference.

## Upload metadata

Native PDF inspection queues an independent `metadata_lookup` job before the full
parse. The worker queries Crossref first by DOI, with DOI Citation Formatter as a
fallback for identifiers not available there. Without a selected DOI, it searches
Crossref using the PDF's embedded title/author or a prominent first-page heading.
Filename-like and missing titles are skipped. Only the DOI or bounded title/author
fields leave the instance; the metadata lookup sends no PDF, body text or provider
credentials. The parser itself does not make network requests.

A standalone arXiv stamp before the first-page body supplies the preprint's
[arXiv-assigned DOI](https://info.arxiv.org/help/doi.html). Version suffixes do not
change that DOI. An explicit DOI in metadata or the first-page header takes
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
