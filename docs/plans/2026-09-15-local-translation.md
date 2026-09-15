# Local translation implementation plan

**Goal:** Add Hy-MT2-1.8B Q8, MiLMMT-46-4B Q4, Hy-MT2-7B Q4 and MiLMMT-46-12B Q4 with on-demand downloads and Docker-managed acceleration.

**Architecture:** A Compose local model service owns a persistent, hash-verified weight cache and talks to Docker Model Runner. Apple Silicon uses MLX affine weights and the existing vLLM Metal backend. A dedicated provider adapter uses native translation prompts and converts plain text into the existing restricted translation AST. External provider configuration, immutable history, permissions, cancellation and unknown outcomes retain their existing contracts.

**Tech stack:** Python/FastAPI/httpx, Docker Model Runner, React/TypeScript, PostgreSQL job/permit workflow.

## Decisions

- User explicitly requires MLX-format weights on Apple Silicon. GGUF/llama.cpp Metal is not an acceptable substitute there.
- Download only the selected model when a translation or explicit preparation needs it. No downloads on settings GET or application startup.
- Pin source revisions, files, byte sizes and SHA-256. Download to temporary files, verify before rename, and only publish a complete model. Use Docker's model load API without mounting the Docker socket.
- Dedicated service has no provider keys, document volumes or database access. It accepts only catalog model identities. Cached models survive container recreation.
- Model selection is explicit; no fallback to another model, hardware or cloud provider. Download/availability failures remain visible.
- One translation unit per inference. Preserve protected references with collision-resistant markers; reject malformed output using existing validation. Translation-only models do not perform semantic review.
- Local settings use the existing CAS and immutable profile store. Keep external saved credentials intact when switching to local inference; no credentials are sent locally.
- Frozen catalog identity and actual runtime/model digest are retained in task evidence. Existing queued profiles and publications remain unchanged.

## Checkpoints

1. Catalog and runtime: write failing catalog/download/packaging tests; implement locked downloads, Docker model packaging/loading and status; verify offline cache reuse, corrupt/interrupted download recovery and unavailable runtime behavior.
2. Provider integration: write failing native prompt/output and profile tests; implement local protocol, settings validation, execution/connection-test routing. Verify single-send, no secrets, identity mismatch, truncation, protected references, CAS and legacy providers.
3. UI and Compose: add local model selector/status/preparation and clear local processing copy; configure isolated service and MLX override. Verify browser interactions, mobile layout, production frontend build and Compose configuration.
4. Runtime verification: use synthetic text through real MLX inference and an isolated PostgreSQL translation workflow, independently review outputs and code. Record actual model/hardware limitations separately. Commit and push verified checkpoints on the configured branch, excluding pre-existing work.

Evidence: `.agent/tmp/local-translation-20260915/`. Persistent testing state: `.agent/local-data/local-translation-20260915/`.

The on-demand download requirement supersedes the older blanket runtime model-download prohibition for these four translation choices only.
