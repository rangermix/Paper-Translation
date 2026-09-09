# AI settings adapter handoff — 2026-09-06

Active user request authorizes editable AI endpoint, key, model settings. Prior d99 release/evidence stays immutable. No actual Provider request or real credential read was performed for this change; all HTTP was `httpx.MockTransport`, and integration tests used independent PostgreSQL schemas.

IR agent owns `packages/providers/openai_responses.py`, targeted `packages/translation/execution.py` wiring, `tests/unit/test_provider_protocols.py`, `tests/integration/test_provider_dispatch_binding.py`. Acceptance owns versioned settings store/API/public config/price validation; root owns Compose/init/ledger changes; web owns the form. Adapter/execution are now ready for independent review and isolated build.

Contract: `endpoint` is the **full request URL**, `api_protocol` is `responses` or `chat_completions`, `auth_mode` is explicit `bearer` or `none` (default bearer). Local/private HTTP is allowed for the user's selected service; URL userinfo/query/fragment/non-http schemes are rejected. `resolve_provider_credentials(frozen_profile)` returns `(endpoint, api_protocol, auth_mode, Path | None)` from the same immutable version. Queued profiles still stop after current configuration changes; an adapter already bound to A captures A's key once and cannot use newly saved B's key. Explicit none never reads a key or sends Authorization.

The historical `OpenAIResponses` class now handles either bound protocol. Chat sends strict `response_format.json_schema`, `n=1`, `max_completion_tokens`, `store=false`, `stream=false`, with no tools/functions. It normalizes prompt/completion/cached/reasoning usage into the existing billing shape without adding reasoning twice. Missing usage remains unknown. Chat tool/unsupported outputs preserve usage for settlement and then stop with `PROVIDER_UNSUPPORTED_RESPONSE`; no protocol fallback occurs. Responses retains the existing safe behavior of ignoring unsolicited non-message objects and validating only message text. Neither executes tools. Transports have redirects/retries/environment proxies disabled.

Semantic review uses the same protocol selection with its distinct strict issue schema and includes target text in the **pre-dispatch** input-size check. No output changes the source IR or marks human review.

Official primary documentation inspected before implementation:
- https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
- https://developers.openai.com/api/docs/guides/structured-outputs
- https://developers.openai.com/api/reference/cli/resources/responses/methods/create (main Responses reference returned a tool error; this official reference supplied the request contract).

TDD/evidence: `provider-protocol-first.xml` 23 failures before adapter support; `provider-protocol-fixed.xml` 26 passed. `provider-dispatch-first.xml` 5 real-PG failures before wiring; `provider-dispatch-fixed.xml` 56 passed including existing locale/authorization paths. Broader final set `provider-protocol-final-targeted-v2.xml` **48 passed**, including semantic review, no-auth dispatch, endpoint/key rotation, unknown usage, unsupported Chat output settlement, original Responses hostile-content/export regression, and retry boundaries. The first broader run's 47 pass/1 fail remains: it detected an over-strict Responses tool-object rejection, which was reverted to the previously verified inert-object behavior without changing the old test.

Independent backend review is `evidence/ai-service-settings/independent-backend-review.md` (not a self-review of my adapter). One A/B idempotency alias finding was fixed by acceptance and independently reprobed; backend/budget tests 44 passed plus two independent probes. New image/actual UI/worker verification is still assigned to root/acceptance/web and must not be claimed from these tests.
