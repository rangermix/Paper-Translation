# Full-page parsing through Docker Model Runner

Surya OCR 2 is the default for new preferences. All executable options process a
complete rendered PDF page through Docker Model Runner (DMR):

| Parser | Pinned weights | Download size (decimal GB) | Output contract |
| --- | --- | --- | --- |
| Surya OCR 2 | `datalab-to/surya-ocr-2` | 1.37 | Layout HTML; normalized block rectangles |
| Chandra OCR 2 | `datalab-to/chandra-ocr-2` | 10.61 | Layout HTML; normalized block rectangles |
| Infinity-Parser2 Pro | `infly/Infinity-Parser2-Pro` | 70.23 | Layout JSON; normalized block rectangles |
| Infinity-Parser2 Flash | `infly/Infinity-Parser2-Flash` | 4.45 | Layout JSON; normalized block rectangles |

The selected revisions, byte counts, hashes, licenses and exact DMR artifact IDs
are in [`parser-vlm-models.lock.json`](../../deployment/parser-vlm-models.lock.json).
Sizes describe downloads, not inference RAM/VRAM. Surya/Chandra have upstream
OpenRAIL terms; Infinity declares Apache 2.0. Inspect those terms before redistribution.

## Shared application image and backend

API, worker, parser and preparation share one amd64/arm64 application image. It
contains PDF inspection/rendering and model-output conversion, without weights,
Torch, Transformers, Paddle, Docling, ONNX or a CUDA inference runtime. PostgreSQL
and Docker's inference engine are separate images/processes.

Set `PARSER_DMR_BACKEND=vllm` for a compatible Linux/WSL2 Docker-managed backend,
or `mlx` for a compatible Apple Silicon Metal backend. `PARSER_DMR_URL` defaults
to `http://model-runner.docker.internal`; a Docker-managed runner with model,
configuration and inference APIs may use an explicit URL. Engine status text
establishes availability, not the engine's actual version or model/image support.

The independently pinned Infinity SDK requires vLLM >=0.26, while its pinned model
cards demonstrate 0.17.1. These are different contracts; the optional translation
runner's 0.19.1 image does not establish compatibility with the newer SDK path.
Select and verify a Docker-managed engine that supports the exact model and image
request. Metal uses a different version scheme. Portable client builds do not
certify a hardware/backend combination. See the
[contract audit](../plans/2026-10-02-parser-gap-audit.md),
[Docker inference engines](https://docs.docker.com/ai/model-runner/inference-engines/)
and [Metal payload setup](mlx-backend.md).

For a new deployment copy the [template](../../compose.example.yaml), configure
DMR, then run:

```sh
cp compose.example.yaml compose.yaml
docker compose build app parser db
docker compose up -d --wait
```

For an existing instance, merge the service/network/cache changes into its ignored
local Compose file while preserving its project name, image pins, backend overrides
and data volumes. A rebuild cannot add missing mounts or services.

## On-demand preparation and isolated execution

Images contain no parser weights. Explicit **准备解析模型** in Settings or first
parsing use downloads only the selected pinned files. Startup and settings reads
or saves do not download or infer. The preparation service owns the writable
`parser_models` cache and receives no PDF, database or translation credential.
The parser mounts the cache read-only and sends page images over its inference
bridge. That bridge is not a domain firewall.

Preparation streams verified files into Docker's OCI model store. Before image
inference the client rechecks the exact artifact ID and effective configuration;
a wrong model/backend fails instead of switching. The cache and DMR each retain a
copy: allow about twice the download size on disk (about 141 GB for Pro), plus
working space and backend memory. Library backups exclude re-downloadable caches.

DMR restricts engine startup flags. The parser sends thinking controls through
each inference request's `chat_template_kwargs`, without adding the rejected
`--default-chat-template-kwargs` startup flag. A rejected configuration now reports
`PARSER_DMR_CONFIGURATION_FAILED`; already verified cached weights can be reused
on the next explicit preparation. Preparation readiness verifies files, imported
identity and configuration, but does not establish successful image inference.

One PDF runs at a time with bounded child resources, deadlines and fence checks.
The parser's 16 GiB cgroup limit applies to its PDF/client work, not Docker's backend
VRAM or Metal process. Cancellation prevents late commits; already submitted
inference may finish. No CPU/CUDA inference framework is installed at runtime.

## Memory budgets and concurrency

Settings → **资源与并发** controls shared RAM/VRAM admission budgets (80% by
default), simultaneous main operations (default 2), and units per operation
(default 1). Auto mode reduces those ceilings using remaining RAM/VRAM; all modes
check the model estimate against measured usage before dispatch. A resident model
is charged once, and pending loads reserve their estimated allocation. Waiting
does not consume an attempt. Existing requests finish when a limit is lowered.
The parser remains serial; llama.cpp can serve concurrent units using its shared
context/cache. Model loading waits for active local requests to finish. The
worker's global ceiling is 16; backend slot limits may be lower.

The managed CUDA Runner exposes private read-only telemetry on port 12435 inside
`model_inference`, with no host port or Docker socket. Rebuild both the application
image and `deployment/vllm-backend` when updating an existing CUDA instance. RAM
is the memory visible to Docker's Linux host/VM, not Windows Task Manager's total;
VRAM is GPU 0, including other processes. Missing GPU telemetry holds local CUDA
work in the queue. External/native runners need equivalent capacity telemetry
configured through `RESOURCE_MONITOR_URL` in the parser and model services before
automatic GPU admission is available. MLX references count unified memory once;
Linux VM RAM telemetry does not measure a native macOS Metal process.

These are admission budgets with estimated headroom, not OS-enforced quotas or
guarantees against other programs allocating memory after a sample. Existing
container cgroup limits still apply independently. Estimates in Settings use
locked weight sizes, full configured context and working-space allowances; they
are deliberately labelled estimates rather than measured peaks.

The pinned CUDA vLLM 0.19.1 image bounds its single-request KV allocation using
vLLM's own attention-group calculation: one full context plus a null block.
The image build fails if the expected upstream implementation changes. Parser
startup also requests a model-sized fraction of device memory instead of an
independent 80% for every model. This removes the unused full-device cache
reservation while keeping model identity, quantization and context unchanged.

## Retired choices and immutable history

Docling/Granite inference is removed. PaddleOCR-VL, Xiaomi and TeleOCR support is
archived under `archive/parsers/`, outside runtime source and Docker build inputs.
TeleOCR's crop-based custom architecture does not fit the selected full-page DMR
scope. Archives are restoration material, not executable product options.

Existing saved IDs, queued snapshots, source revisions and published readers are
not reassigned or rewritten. Settings displays retired choices as inactive; select
an active parser explicitly for new work. A queued retired/native task fails with
an actionable unavailable-parser result. Existing source remains usable for
translation, reading and export without re-parsing.

Model markup is data rather than a webpage. Shared PDF recovery and nonblocking
quality checks remain active. The versioned semantic bridge is tracked by the
[specification and implementation plan](../plans/2026-10-02-dmr-parser-spec.md).
Source capability, offline regression results and actual model/hardware evidence
must be recorded separately. No live inference claim follows from a build or test double.
