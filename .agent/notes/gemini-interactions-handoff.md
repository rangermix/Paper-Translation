# Gemini Interactions implementation handoff

2026-09-06. Owner `/root/ir_publisher_parser`.

New owned files: `packages/providers/gemini_interactions.py` and `tests/unit/test_gemini_interactions.py`. Pure `request_body(units, profile, glossary, *, review=False)` / `normalize_response(data, http_response)` are ready. The complete endpoint example is `https://generativelanguage.googleapis.com/v1beta/interactions`; protocol `gemini_interactions`, provider `gemini`, API-key header `x-goog-api-key`, or explicit unauthenticated custom destination. Parent owns shared HTTP, registry, billing, secret files, execution and tests of those paths.

Current JSON format is response_format text/application-json/schema and response steps/model_output/content/text. Six usage counters are required for supported text-only settlement: total_input_tokens, total_cached_tokens, total_output_tokens, total_thought_tokens, total_tool_use_tokens, total_tokens. Cached input is included in input; output and thought are additive. Thought content is never published. Unsupported content retains known usage; inconsistent or unpriced accounting is unknown.

42 local unit cases pass; first failures retained. Official sources and limitations are in `evidence/gemini-claude/gemini-official-contract-review.md`. This is not live Gemini certification. No real model request or key read occurred. `store=false` is an API request, not a claim of zero provider retention. Complete URL is never rewritten or replaced by another API.

Peer `/root/acceptance_harness` independently reviewed Gemini and reran all 42 tests: `evidence/ai-native-providers/gemini-independent-review.md`. This agent independently reviewed Claude (38 author tests + 8 new pure probes) in `evidence/gemini-claude/independent-claude-review.md`.

This agent found and reproduced the root common native transport's missing response-model check (4 failures), then independently verified the fix and four additional prefix/immutable-model boundaries (8 passed). Shared native/PG/settings scope: 45 + 10 tests passed; report `evidence/gemini-claude/independent-shared-native-review.md`, exact reviewed files in the adjacent `independent-shared-native-files.json`. No current blocking finding in those scoped reviews. Runtime images and actual browser verification belong to the parent/other agent, and are not silently inferred from these tests.
