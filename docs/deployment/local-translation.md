# Local translation and paper analysis

Settings → AI service → **本地翻译模型** selects model family, parameter size and
quantization, format, then the exact Docker Model Runner model ID. An independent
**推理后端** selector follows the model ID. The pinned
translation catalog currently includes:

| Format and engine | Pinned repositories | Deployment capability |
| --- | --- | --- |
| GGUF / llama.cpp | tencent/Hy-MT2-1.8B-GGUF and tencent/Hy-MT2-7B-GGUF; mradermacher/MiLMMT-46-{1B,4B,12B}-v0.1-GGUF; all Q4_K_M | Docker hosts with a supported llama.cpp backend |
| Safetensors / vLLM | tencent/Hy-MT2-1.8B, BF16 | Docker Model Runner deployment with supported NVIDIA CUDA vLLM (Linux x86_64 or supported Windows WSL2) |
| MLX / Docker-managed vLLM Metal | mlx-community/Hy-MT2-1.8B-8bit, shraey/milmmt-46-4b-mlx-4bit, mlx-community/Hy-MT2-7B-4bit, mlx-community/MiLMMT-46-12B-v0.1-4bit | Apple Silicon macOS with the provisioned MLX backend |

Each pinned model declares its reviewed `inference_backends`; the model's default
engine is retained for old configurations. Choices are the intersection of those
compatibilities and the deployment's supported backends. Installation, engine
readiness and downloaded weights are reported for the selected backend separately.
The current catalog offers the combinations in the table. GGUF through vLLM is
not integrated with this Runner adapter yet and is not offered as a working choice.
Compatibility metadata does not change a model's pinned artifact ID.

`LOCAL_TRANSLATION_FORMATS` declares the formats supported by this deployment,
for example `gguf`, `gguf,mlx`, or `gguf,safetensors`. The sidecar has no Docker
socket or host hardware access, so set this in the instance's local Compose
environment after checking the host and Docker Model Runner engine support.
The default is GGUF, or GGUF plus MLX when the Mac's pinned Paddle MLX model is
declared. Pass the same declaration to app, worker and local-translator; the
template's shared app environment and sidecar environment already do this. When
upgrading an older local Compose file, add both environment entries there too.
The API reads the pinned catalog even when the optional sidecar is stopped, so
model families remain selectable and saveable while service status is unavailable.
An engine may be supported but not installed, running, or able to fit
a selected model. Those conditions appear as model status and do not remove a
supported format from the selector. Docker Model Runner can package Safetensors
on other hosts, but packaging alone does not provide vLLM inference there.

`LOCAL_TRANSLATION_BACKENDS` optionally declares supported engines independently,
using `llama.cpp`, `vllm` and `mlx` (for example `llama.cpp,vllm` on a supported
CUDA Linux/WSL2 deployment). Leave it empty to derive the existing engines from
`LOCAL_TRANSLATION_FORMATS`. Declare `mlx` only on Apple Silicon macOS, and `vllm`
only where the deployment's platform and hardware support CUDA vLLM. Pass the same
value to app, worker and local-translator using the template's environment entries.
This declares capability; it does not require the engine to be installed or started.

The settings form remembers backend choices for each exact model while switching
family, size, format or interface. Saving writes `local_backend` to the versioned
provider profile and the public task configuration snapshot. New tasks use this
saved backend for preparation, status and inference. Existing immutable profiles
without this field continue to use the original model default; viewing them does
not rewrite their revision or hash. Changing the saved backend does not change
an already started task. A saved incompatible backend is shown explicitly and
must be corrected before saving; no engine is substituted silently.

The MiLMMT GGUF files are community quantizations of Xiaomi's v0.1 checkpoints;
their repository revisions, file sizes and LFS SHA-256 values are pinned separately
from the MLX variants. They use the same native translation completion prompt.
Catalog entries do not assert that inference has been tested on this instance.

Translation preparation also offers a separate **MiniCPM5-1B Q4 analyst**, pinned
to [openbmb/MiniCPM5-1B-MLX](https://huggingface.co/openbmb/MiniCPM5-1B-MLX)
revision `9879b18bf2928355fcdf4287635388a3665a40cb`.
The seven verified files total 617,970,878 bytes (about 590 MiB), before DMR's imported
copy and runtime allocations. It is selected in translation preparation, separately
from the translator in service settings. It can prepare context for an API translator
as well as a local one. This is not a CPU/CUDA analyst backend.

Apple Silicon uses MLX safetensors through the same Docker Model Runner
vLLM Metal backend as PaddleOCR. These are MLX affine quantizations, not GGUF.
The GGUF path uses llama.cpp and may run on CPU or a supported GPU. Safetensors
uses the standard vLLM backend and requires a supported NVIDIA CUDA environment.
No path silently chooses a different format, model, or remote provider.

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

Local analyst requests use a bounded structured brief/term contract with reasoning
disabled. The runtime context is 8,192 tokens, with application ceilings of 6,144
input and 2,048 output; the input uses a conservative UTF-8 byte guard including the
schema and template. Only selected source excerpts reach the analyst. A malformed
settled suggestion produces an extraction fallback warning, without another model
request. Downloads/model loading and inference are separate from merely viewing a
saved preparation. Source and consent are rechecked before content dispatch.

With local preparation followed by API translation, selected context is subsequently
sent to the explicitly confirmed API translator. Local analysis alone does not make
the combined workflow local-only.

The application uses each model family's native translation prompt and restores
protected references outside the model. It never asks a translation-only model
to produce the application's JSON or modify the source. Semantic review is
unavailable for these translation-only models. Existing quality warnings,
immutable history, dispatch controls and handling of uncertain requests remain
in effect. Task records include the returned artifact ID and pinned revision.

Hy prompts explicitly translate ordinary prose and spelled-out numbers into the
requested language. A nonblocking quality check reports newly introduced Hangul
or kana when that script is unexpected for the target locale and absent from the
source and applicable glossary terms. It preserves legitimate Korean/Japanese
targets, source names and quotations. This is a narrow script check, not a
translation-accuracy certificate; it neither substitutes words nor retries a
model request automatically. Prepared Hy-MT requests use bounded background following
the upstream [background/source pattern](https://huggingface.co/tencent/Hy-MT2-1.8B#hy-mt2-translation-task-instruction-examples-chinese-english-comparison).
MiLMMT receives applicable terms only. Legacy requests still omit neighboring prose.
Preparation changes participate in cache identity; the unchanged legacy prompt keeps
its existing request-format version.

## Compose deployment

The `local-translation` profile is included in
[`compose.example.yaml`](../../compose.example.yaml). For an existing deployment,
add its `local-model-init` and `local-translator` services and their network/cache
declarations to the preserved local `compose.yaml`; keep the app/worker connections
to the internal model-control network. New copies already contain these definitions.
Declare the supported formats for the host in the local environment file.
On Apple Silicon, prepare the [MLX backend](mlx-backend.md) and select the
local file's MLX parser mode as described in [acceleration](extraction-acceleration.md).
Build the app image and start the optional services:

```sh
docker compose build app
docker compose --profile local-translation \
  up -d --no-build --wait app worker local-translator
```

Keep `--profile local-translation` when starting this configuration, or set
`COMPOSE_PROFILES=local-translation` in the instance's local environment file.

Enabling Docker Model Runner in Docker Desktop does not start the application's
optional sidecar. Keep the profile enabled for that sidecar. It also does not prove
an inference engine installed successfully. The settings page reports backend
installation failures separately from the pinned model catalog.

The sidecar runs from the app image with a read-only root filesystem and only its
own cache volume. It has no document, database, provider-secret or Docker-socket
mount. Compose startup does not download any translation model. The API and
worker reach it on an internal control network; its other network reaches DMR
and pinned weight repositories. No runtime pip/npm installation occurs.

## Windows Runner diagnostics

Read the connected Runner's `/engines/status` endpoint before changing CORS,
ports or GPU drivers. The application calls it from the sidecar, so browser CORS
does not control this connection. A Windows Runner may fail CUDA detection because
`com.docker.nv-gpu-info.exe` is missing from the user's inference directory even
though the installed Docker Desktop bundle contains it. This is tracked in
[Docker Model Runner issue 1054](https://github.com/docker/model-runner/issues/1054).
Restore only that helper from the same installed Desktop bundle, then retry the
existing Runner's `/engines/install-backend` endpoint with `{"backend":"llama.cpp"}`.
Some Runner builds mark the initial failed installation as completed internally,
so a retry can return HTTP 200 while `/engines/status` still reports the old error.
If this occurs, wait for active llama.cpp requests to finish, reset only that
backend with `/engines/uninstall-backend`, then retry installation and inspect
the status again. Never interpret HTTP 200 alone as a running backend.
Preserve existing models, GPU settings and the Runner's other backends. Backend
updates may remove the helper again, so recheck the specific failure if it recurs.

Windows with WSL2 and a supported NVIDIA GPU can provide CUDA vLLM, as described
in [Docker's inference engine guide](https://docs.docker.com/ai/model-runner/inference-engines/).
A native Windows Runner build can still report `Not Installed: only supported on
Linux`. That reports the connected Runner's deployment, not lack of hardware
support. Declare Safetensors when provisioning the supported Linux/WSL2 vLLM
deployment; its unavailable status stays visible until that backend is connected.
The application never replaces the selected endpoint or backend automatically.

### CUDA vLLM through Compose on Windows/WSL2

Use the optional `local-vllm` profile to run a Linux Docker Model Runner on the
existing Docker Desktop WSL2 engine. Its pinned backend image rebuilds the Python
environment with vLLM 0.19.1 and CUDA 13.0 PyTorch wheels, including locked package
hashes. The final image uses a clean, pinned NVIDIA CUDA base, retaining the Runner
and its rebuilt environment without Docker Desktop's reserved internal-service
label. It verifies a CUDA tensor operation before exposing the Runner API.
The host must support NVIDIA GPU passthrough; no Linux GPU driver is installed by
this deployment. No translation weights or inference requests occur at startup.

This avoids observed upstream setup failures: Model Runner CLI v1.2.6 tests
the Docker Engine's operating-system string for exact equality with `Docker Desktop`,
which misses `Docker Desktop (containerized)`; and the current
`latest-vllm-cuda` image can contain CPU-only PyTorch, as reported in
[Docker Model Runner issue 952](https://github.com/docker/model-runner/issues/952).
The upstream image also carries `com.docker.desktop.service=model-runner`, which
hides containers from Compose discovery on Docker Desktop. Setting that label to
an empty value still hides the container, so the final image omits the key entirely.
The usual CLI setup can also collide with an existing native Runner's TCP port
12434. This Compose service exposes no host port and keeps the native Runner intact.

After inspecting the actual host, preserve the instance's local configuration and
add the `vllm-runner` service and `local_vllm_models` volume from the template.
Add `LOCAL_VLLM_DMR_URL` to the local-translator environment, as in the template.
Set these instance environment entries:

```dotenv
COMPOSE_PROFILES=local-translation,local-vllm
LOCAL_TRANSLATION_FORMATS=gguf,safetensors
LOCAL_VLLM_DMR_URL=http://vllm-runner:12434
```

Build and start the selected services:

```sh
docker compose build app vllm-runner
docker compose up -d --no-build --wait app worker local-translator vllm-runner
docker compose exec vllm-runner curl -fsS http://localhost:12434/engines/status
```

`LOCAL_VLLM_DMR_URL` applies only to CUDA Safetensors models. GGUF and MLX use
their existing native Runner by default. GGUF can independently select a Runner
with `LOCAL_GGUF_DMR_URL`; MLX continues to use the native endpoint. A failure of
a selected Runner keeps catalog entries available and never changes the selected
model or forwards the request to another backend. All paths use the existing
exact artifact-ID checks and pinned download cache.
The separate Runner stores imported artifacts in `local_vllm_models`; the
sidecar's existing cache volume is retained. This endpoint accepts DMR APIs,
not a standalone OpenAI-only vLLM service.

If the native Windows Runner rejects model import with a `missing blob` error
after the weight files pass validation, set
`LOCAL_GGUF_DMR_URL=http://vllm-runner:12434` for local-translator. The same Linux
Compose Runner provides llama.cpp for GGUF. The native Windows tar importer in
[DMR v1.2.8](https://github.com/docker/model-runner/blob/v1.2.8/pkg/distribution/tarball/reader.go)
cleans paths with Windows separators but splits them on `/`, skipping the archive's
blobs. Selecting the Linux importer preserves the pinned model identity and reuses
the verified cache. Add the sidecar environment entry from the template to an
older local Compose file, recreate local-translator, then prepare the exact model
and resume the waiting job. Model-import HTTP failures report
`LOCAL_MODEL_LOAD_FAILED` separately from weight-download failures.

llama.cpp can report a weight-file path as the response model. For GGUF, the
provider recognizes only the exact Linux DMR bundle path containing the pinned
artifact digest and its verified filename. The canonical model ID is checked
against the saved profile; any other digest, filename or path remains a model
mismatch. Task history keeps the original name in `reported_model_id` and records
the actual engine (`llama.cpp`, `vllm` or `mlx`). DMR reserves `--alias`, so the
application does not configure this disallowed runtime flag.

The CUDA startup check establishes runtime/GPU availability, not that a selected
model fits or produces a correct translation. Those require explicit model
preparation and separately authorized inference. GPU memory is shared with the
parser and any other application on the device.

## Apple Silicon MLX backend payload

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
larger MLX memory allowance applies only to the exact translation and analyst model
identities in the pinned catalogue. Paddle retains its original allocation. Rebuild
this extension when adding the analyst to an existing installation, because the
backend's owned-model allowlist is generated from that catalogue at build time.

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
