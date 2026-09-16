# PDF extraction acceleration

Deployment always uses Docker Compose. PaddleOCR-VL-1.6 is the default for new work when no preference has been saved. Explicit saved choices, queued profiles, sources and publications stay unchanged. Jobs that predate parser selection still use Docling.

| Deployment | Image build | Paddle recognition | Paddle layout | Docling / Granite |
|---|---|---|---|---|
| CPU | `PARSER_FLAVOR=cpu` | CPU | CPU | CPU |
| NVIDIA | `PARSER_FLAVOR=cuda` (unified) | CUDA | CUDA | CUDA; RapidOCR remains ONNX CPU |
| Apple Silicon (verified local Docker backend) | Same CPU image + Docker Model Runner | MLX through vLLM Metal | CPU | CPU |

The unified CUDA image contains two isolated, frozen Python environments because PyTorch and Paddle require conflicting cuDNN/NCCL versions. They share one model directory and one parser implementation. The parser chooses the Paddle CUDA interpreter for Paddle jobs; all other jobs use the main interpreter. The unified image can also run CPU workloads with `PARSER_ACCELERATOR=cpu`. The lighter CPU image remains the default download.

Settings shows the parser service’s detected operating system, architecture, CPU quota, memory ceiling and GPU name. Users can choose a runtime supported by the selected model and deployed image; unavailable choices include a reason. The capability report refreshes every minute and expires when the parser heartbeat is stale. API validation rejects unavailable explicit choices. Each new job freezes its resolved runtime in the queue and spool, independent of later preference or deployment-default changes. Existing queued jobs retain their original behavior. Endpoints and image provisioning remain deployment configuration; users cannot supply parser endpoints through the API. Actual device, backend and the MLX model artifact ID are recorded with each parsing attempt. CUDA selection fails if the required interpreter or GPU is unavailable. No automatic CPU/model/provider fallback is added. Existing bounded page recovery and nonblocking quality warnings remain.

MLX becomes available only after setup records successful image inference for the packaged model. The heartbeat rechecks a running Metal backend and model metadata; clear and refresh the setup receipt after model/backend changes. CPU availability indicates that the runtime is installed, not that a particular PDF will fit in memory; Settings warns when Paddle is selected with less than 10 GiB of usable memory. No host hardware is inferred from the Linux container.

## CPU

From the repository root:

```sh
docker compose -f deployment/compose.production.yaml up -d --build
```

All weights are downloaded and hash-checked during image build. The CPU parser remains `network_mode: none`.

Size Docker's VM memory for the model as well as other running services. On the tested 16 GB Mac with an 8 GB Docker VM, Paddle was OOM-killed during model loading, including a repeat after this task's builds and probes stopped. Docling completed the controlled sample. The parser's 16 GiB cgroup ceiling does not allocate extra memory to Docker's VM. Failed extraction preserves the PDF and does not automatically retry or change the selected model.

## NVIDIA CUDA

Requires Linux x86_64 (or a compatible Docker Desktop WSL2 GPU host), an NVIDIA driver compatible with CUDA 12.6, and Docker GPU support. No host Python or CUDA Python packages are installed.

```sh
docker compose -f deployment/compose.production.yaml -f deployment/compose.cuda.yaml up -d --build
```

Only the parser receives one GPU; it stays network-isolated. The image's main environment pins PyTorch 2.9.1/cu126 and Paddle CPU 3.3.1. Its Paddle environment pins Paddle GPU 3.3.1/cu126 and CPU PyTorch. Each full dependency graph has its own `uv.lock`; dependency overrides are not used to suppress CUDA ABI conflicts. Docling VLMs use FP16 on CUDA and FP32 on CPU. RAM is still bounded to 16 GiB; this cgroup limit does not cap GPU VRAM. One PDF runs at a time with its existing frozen timeout and cancellation/fence checks.

## Apple MLX, managed by Docker Compose

**2026-09-13 tag preference:** use the floating model reference `docker.io/local/paddleocr-vl-1.6:latest`. This is a locally packaged model tag, not an automatically updating upstream release. Use the full `docker.io/` reference in Compose: the tested CLI attempted a registry pull for the abbreviated local reference but successfully reused the full reference. Resolve its current content ID during setup and keep that ID in `PADDLE_MLX_MODEL_ID` for request validation and actual-model records. Repackaging the tag requires refreshing this value before deployment. Docker Desktop separately selects its inference backend package; the installed CLI has no vLLM Metal version override, and Docker currently publishes no floating vLLM Metal backend tag. The generic `docker/model-runner:latest` Linux image is not an Apple MLX backend.

**Successful local repair, 2026-09-13:** a custom Docker-built `darwin/arm64` backend image, `local/paper-translation-vllm-metal:latest`, now supplies vLLM/vLLM Metal 0.29.0 to Docker Model Runner. It fixes the `max_pixels` preprocessing failure and includes real Paddle vision execution. Two synthetic image requests returned the exact expected text, then the running application completed a controlled PDF extraction with MLX recognition and CPU layout. The original PDF was preserved byte-for-byte. Production MLX is active at localhost:8080. This is a local custom backend, not an official updated Docker package. Build, activation, memory settings, verification and rollback are described in [mlx-backend/README.md](mlx-backend/README.md); evidence is `.agent/tmp/mlx-repair-20260913T125316Z/verification.md`.

Requires Apple Silicon Docker Desktop with Docker Model Runner and a compatible **vLLM Metal** backend. Docker's published `v0.2.0-20260420-142150` payload still fails this workload and skips vision encoding. The local repair replaces only DMR's backend payload, preserving its process management. Linux containers cannot directly access Apple Metal. No separate host Python server is installed.

Provision/check Docker's backend before using the MLX override:

```sh
docker model install-runner --backend vllm
docker model status
```

Compose declares the model with its `models` section (Compose 2.38+); Docker manages its runtime and lifecycle. There is no separately installed Python server, launch agent, host virtualenv, Docker socket mount, or application reverse proxy. Docker Model Runner itself is part of the Docker platform setup. Its backend dependencies and model artifact must be provisioned before offline operation; parsing never installs a backend or pulls weights.

Build/package the model once using the exact files already locked into the parser image:

```sh
# Use an empty, writable absolute directory for the build output.
export MODEL_EXPORT_DIR=/absolute/path/to/model-build-output
docker compose -f deployment/compose.model-package.yaml run --build --rm model_export

# This is artifact packaging into Docker's local model store, not a host service.
docker model package \
  --safetensors-dir "$MODEL_EXPORT_DIR/paddleocr-vl-1.6" \
  --license "$MODEL_EXPORT_DIR/paddleocr-vl-1.6/LICENSE" \
  local/paddleocr-vl-1.6:latest

docker model inspect local/paddleocr-vl-1.6:latest
```

Record the full `id` (`sha256:` plus 64 hex digits) from the inspection output. Set these deployment values in your shell or Compose environment file:

```sh
export PADDLE_MLX_MODEL=docker.io/local/paddleocr-vl-1.6:latest
export PADDLE_MLX_MODEL_ID=sha256:REPLACE_WITH_THE_ACTUAL_INSPECTED_MODEL_ID
# Only after an actual image request succeeds on the provisioned backend:
export PARSER_MLX_VERIFIED_MODEL_ID="$PADDLE_MLX_MODEL_ID"
docker compose -f deployment/compose.production.yaml -f deployment/compose.mlx.yaml up -d --build
```

The placeholder above deliberately fails validation. No model digest is invented in source control. Preserve the resolved model ID with the image/build evidence; do not use an unrelated Paddle version or a quantized replacement under this tag. For registry distribution, publish the built artifact separately and use its floating registry tag for `PADDLE_MLX_MODEL`, resolving its actual content ID during setup.

The parser first checks a running Metal backend and reads local DMR model metadata and requires the expected content ID and safetensors format. If Docker includes architecture metadata, it must match Paddle; Docker Model Runner 1.2 omits this field for locally packaged safetensors. Requests then use that content ID, rather than a mutable tag. They go to the fixed `/engines/vllm/v1` endpoint, which selects vLLM Metal on Apple Silicon instead of DMR's automatic engine fallback. Missing models/backends fail; no translation-provider credentials are sent. Only local page-region images go to Docker's runtime. The MLX override gives the parser a dedicated bridge to reach DMR; unlike the CPU/CUDA modes, it is not network-none. This bridge is not a domain-level firewall.

MLX acceleration applies to Paddle's VLM stage. Other profiles retain CPU execution and report it explicitly. The container's memory limit does not cap the Docker-managed host model process; configure Docker Model Runner for the Mac's available unified memory. The existing PDF deadline/cancellation stops the parser and prevents late output commits; an already submitted DMR inference may finish after cancellation.

## Verification and boundaries

Relevant checks: parser acceleration/default/timeout/cancellation tests, task ModelIdentity schema validation, parser settings browser tests, frontend unit/build tests, and frozen lock resolution. A real CPU/CUDA/MLX acceptance run must additionally build the images, cold-start Compose, parse a controlled PDF, inspect actual task records, and confirm no runtime downloads. YAML checks and mocked DMR metadata are not hardware or model-quality certification.

Live verification on 2026-09-10 built both CPU and unified CUDA images, started the Compose stack at localhost:8080, completed controlled Docling extraction, and verified model export/packaging plus DMR metadata access from the MLX Compose service. The CUDA image's main environment imports successfully; its GPU Paddle environment requires the NVIDIA driver library absent on this Mac, so CUDA inference is not certified. Paddle CPU inference remains blocked by the observed VM memory limit; Apple image inference was subsequently repaired and verified on 2026-09-13 with the custom Docker backend described above. No paid provider calls were made. Detailed local evidence is in `.agent/tmp/extraction-20260910/verification.md`.

Sources checked 2026-09-09: [Docker Compose GPU support](https://docs.docker.com/compose/how-tos/gpu-support/), [Compose models](https://docs.docker.com/ai/compose/models-and-compose/), [Docker vLLM Metal architecture](https://www.docker.com/blog/docker-model-runner-vllm-metal-macos/), [vLLM Metal supported models](https://github.com/vllm-project/vllm-metal/blob/main/docs/supported_models.md), [Docker model packaging](https://docs.docker.com/reference/cli/docker/model/package/), [DMR API](https://docs.docker.com/ai/model-runner/api-reference/).
