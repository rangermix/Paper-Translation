# Local translation verification — 2026-09-15

Implemented on `main` in `b34136c` and `13dce0f`, followed by the idle-model
handoff fix. Pre-existing parser and reader work was excluded from these commits.

## Verified

- **71 focused unit tests**: pinned catalog, hash-checked cache/download recovery,
  model packaging, native prompts, protected references, configuration and key
  restoration, output/model mismatch, and bridge failure classification.
- **38 PostgreSQL integration tests**, including local preparation before permit
  allocation, exact returned model/revision recording, stale-profile rejection,
  and existing external-provider execution/connection tests.
- **20 Playwright checks** at desktop and mobile sizes; production frontend build
  passed. The deployed `http://127.0.0.1:8080/#/settings` also displayed all four
  models without console errors or any mutation/download from selecting them.
- **Real Apple M4 MLX inference** through the Compose sidecar and Docker Model
  Runner for Hy-MT2-1.8B Q8 and MiLMMT-46-4B Q4. Both translated two synthetic
  English sentences into Chinese and returned their exact pinned artifact IDs.
- **Real worker workflow** in an isolated PostgreSQL schema: Hy-MT2 translated
  nine segments in 48.09 seconds over nine settled requests. Source bytes were
  unchanged. The test schema and container were removed afterward; production
  provider configuration and credentials were not used or changed.
- **Paddle regression proof** on the updated backend: two exact image-dependent
  OCR results (`MLX 123`, `GPU 789`) and a complete controlled PDF extraction in
  55.47 seconds. The PDF remained byte-identical. Its temporary document was
  removed after evidence capture. The Paddle setup receipt was restored.
- App, worker, parser and local-translator were deployed through Compose.

MiLMMT's initial cache allocation of approximately 6.97 GB was reduced to 1.14 GB
(one 8,192-token context plus the reserved block). Runtime logs confirm the
513-block allocation, MLX GPU execution and successful inference. The backend
payload remains managed by DMR; no standalone host inference service was added.

## Validation boundaries

Hy-MT2-7B Q4 and MiLMMT-46-12B Q4 are pinned and selectable, but their weights were
not downloaded for this verification. Their first use prepares them on demand;
this report does not claim that either model fits this 16 GB Mac. CPU/CUDA and
other machines were not certified. No paid/cloud provider was called.

The final independent review found no remaining concrete issue in GPU handoff
or pre-send/unknown-outcome classification. DMR protects active runner references
when unloading; the bridge also checks its unload result before proceeding.

## Evidence and recovery

Run evidence is under `.agent/tmp/local-translation-20260915/`:
`unit-release.log`, `integration-final.log`, `browser-final/`, `live-ui-2.log`,
`hy18-inference.log`, `mi4-bounded-inference.log`, `live-job-3.log`,
`paddle-images.log`, and `pdf-proof/`.

The Docker-built backend is `local/paper-translation-mlx-translator:20260915`.
Its bounded payload manifest is
`sha256:34f2077a6f39381cc5ec650e01f788dfd67ee32924512b368029eca122d61eb1`.
The original Paddle backend and environment are preserved in
`.agent/local-data/local-translation-20260915/paddle-backend-before` and
`mlx.env.before`. Restore backend directories only with inference idle and the
Paddle receipt cleared, then reverify image inference before restoring it.
