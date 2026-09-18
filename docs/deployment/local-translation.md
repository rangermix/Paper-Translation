# Local translation with MLX

Settings → AI service → **本地翻译模型（MLX）** offers:

| Option | Pinned MLX repository | Quantization |
| --- | --- | --- |
| Hy-MT2-1.8B Q8 | mlx-community/Hy-MT2-1.8B-8bit | 8 bit |
| MiLMMT-46-4B Q4 | shraey/milmmt-46-4b-mlx-4bit | 4 bit |
| Hy-MT2-7B Q4 | mlx-community/Hy-MT2-7B-4bit | 4 bit |
| MiLMMT-46-12B Q4 | mlx-community/MiLMMT-46-12B-v0.1-4bit | 4 bit |

Apple Silicon uses MLX safetensors through the same Docker Model Runner
vLLM Metal backend as PaddleOCR. These are MLX affine quantizations, not GGUF.
The local translation service requires Apple Silicon and the Docker-managed Paddle MLX backend;
the current implementation does not provide a CPU/CUDA local-translation backend.

## Download and use

Saving or selecting a model does not download weights or send an inference
request. The first translation/test prepares the selected model automatically.
**立即准备模型** downloads it explicitly. All other models remain untouched.
Files are cached in the `local_translation_models` Docker volume. Each file is
checked against its fixed revision, byte size and SHA-256 in
`src/packages/local_models/models.lock.json`. Interrupted or corrupt files are not
published; retry retains previously verified files. DMR also keeps its imported
model artifact. Allow disk space for both copies.

No API key is required. Document text goes only to the local service and DMR;
Hugging Face receives weight-download requests, not document content. Switching
back to a saved API configuration retains its existing secret binding. There
is no automatic fallback to another model or cloud provider.

The application uses each model family's native translation prompt and restores
protected references outside the model. It never asks a translation-only model
to produce the application's JSON or modify the source. Semantic review is
unavailable for these translation-only models. Existing quality warnings,
immutable history, dispatch controls and handling of uncertain requests remain
in effect. Task records include the returned artifact ID and pinned revision.

## Compose deployment

The `local-translation` profile is included in
[`compose.example.yaml`](../../compose.example.yaml). For an existing deployment,
add its `local-model-init` and `local-translator` services and their network/cache
declarations to the preserved local `compose.yaml`; keep the app/worker connections
to the internal model-control network. New copies already contain these definitions.
Prepare the [MLX backend](mlx-backend.md) and select the local file's MLX parser mode
as described in [acceleration](extraction-acceleration.md), then build the app image
and start the optional services:

```sh
docker compose --env-file .env.mlx build app
docker compose --env-file .env.mlx --profile local-translation \
  up -d --no-build --wait app worker local-translator
```

Keep `--profile local-translation` when starting this configuration, or set
`COMPOSE_PROFILES=local-translation` in the instance's local environment file.

The sidecar runs from the app image with a read-only root filesystem and only its
own cache volume. It has no document, database, provider-secret or Docker-socket
mount. Compose startup does not download any translation model. The API and
worker reach it on an internal control network; its other network reaches DMR
and pinned weight repositories. No runtime pip/npm installation occurs.

## Docker-managed backend payload

The Paddle backend image must already exist as
`local/paper-translation-vllm-metal:latest`. Build the translation extension:

```sh
TASK_DIR=".agent/tmp/translation-backend-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$TASK_DIR"
docker buildx build --platform darwin/arm64 \
  -f deployment/local-translation-backend/Dockerfile \
  --output "type=oci,dest=$TASK_DIR/translation-backend.oci.tar" \
  -t local/paper-translation-mlx-translator:latest .
```

The extension preserves the
Paddle runtime and fails the build if its reviewed source anchors change. It
routes quantized Gemma3 text checkpoints through MLX-LM and caps the translation
KV cache to one configured context plus the scheduler's reserved block. The
larger MLX memory allowance applies only to the four exact translation model
identities. Paddle retains its original allocation.

Install using the existing Paddle backend procedure: stop new parsing, wait for
active inference, clear `PARSER_MLX_VERIFIED_MODEL_ID`, preserve the full existing
DMR backend directory, extract the Docker-built macOS payload and replace that
directory. DMR owns and launches the process. Do not start an independent host
server or overlay different versions of site-packages. Restore the Paddle
receipt only after real image inference and a controlled PDF check succeed.

Only idle project translation models and the explicitly configured Paddle ID
may be unloaded when switching models. An active or unrelated model produces a
busy failure. Larger models require more unified memory; a 12B model is not a
promise of fitting every Mac. Resource failures do not choose a different model.
DMR unload removes runtime configuration, so preparation rechecks the effective
flags before inference. The UI's downloaded state describes cache availability,
not proof that inference can fit or succeed on the current machine.

The catalog and model file hashes are maintained in
[`models.lock.json`](../../src/packages/local_models/models.lock.json). Inspect the
pinned upstream license/model-card metadata before redistributing weights. A listed
model is selectable, not proof that it has run successfully on the current host.
