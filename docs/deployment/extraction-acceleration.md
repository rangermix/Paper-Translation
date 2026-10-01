# PDF extraction acceleration

New preferences default to PaddleOCR-VL-1.6. Saved preferences and queued jobs
retain their selected profile; legacy tasks without a profile keep their existing
Docling behavior. The active mode in Compose determines the device; saved device
overrides from older settings are ignored. Settings shows the effective device
and reads the parser environment when opened. Model preparation status is polled.
A new job freezes its resolved model, device and timeout when the parser environment
is available. If the parser is offline, it applies its Compose mode when execution
starts. Existing queued devices are not rewritten.

| Deployment | Build/runtime | Paddle recognition and layout | Docling / Granite |
| --- | --- | --- | --- |
| CPU | Default parser image | CPU / CPU | CPU |
| CUDA | Unified CUDA image | CUDA / CUDA | CUDA; RapidOCR uses ONNX CPU |
| Apple MLX | CPU parser image plus Docker Model Runner | MLX / CPU | CPU |
| DMR | Portable lightweight parser client plus Docker Model Runner | Not provided by this mode | Not provided by this mode |

Images contain no parser weights. Explicit preparation in Settings or the first
parse downloads only the selected profile's dependencies into the persistent
`parser_models` volume. Reading/saving settings and startup never download weights.
CPU/CUDA parsers connect only to the internal preparation network. The separate
preparation service has download access and never receives PDF content or secrets.
The CUDA build uses separate Torch/Paddle environments because their native GPU
libraries conflict. TeleOCR has a pinned Transformers 4.57 environment that shares
the main Torch runtime; its custom code is incompatible with Transformers 5.17.
All native environments share the same parser code and read-only model directory.

Copy [`compose.example.yaml`](../../compose.example.yaml) to local `compose.yaml`
only for a new deployment. CPU mode is enabled by default. To select CUDA on a
host with a compatible NVIDIA driver and Docker GPU support, comment the CPU mode
block and uncomment the CUDA mode block in that local file. Keep exactly one mode
active, then use the same commands for the selected mode:

```sh
docker compose build app parser db
docker compose up -d --wait
```

The parser handles one PDF at a time with bounded process resources, deadlines and
fence checks. Its 16 GiB cgroup ceiling does not allocate memory to Docker's VM
or constrain GPU VRAM. Runtime availability is not proof that a chosen PDF/model
fits in available memory. Failed device/model selection does not silently fall back.

## Additional parser options and Docker Model Runner

The public options include the latest pinned upstream Surya/Chandra generations:

| Parser | Pinned weights | Download size (decimal GB) | Execution |
| --- | --- | --- | --- |
| Surya OCR 2 | `datalab-to/surya-ocr-2` | 1.37 | Native CPU/CUDA or DMR |
| Chandra OCR 2 | `datalab-to/chandra-ocr-2` | 10.61 | Native CPU/CUDA or DMR; substantial RAM required |
| Infinity-Parser2 Pro | `infly/Infinity-Parser2-Pro` | 70.23 | DMR; sufficient backend memory/VRAM required |
| Infinity-Parser2 Flash | `infly/Infinity-Parser2-Flash` | 4.45 | Native CPU/CUDA or DMR |
| TeleOCR | `XingChen-AGI/TeleOCR` | 2.85 | Native CPU/CUDA with pinned custom Transformers code |
| Xiaomi-OCR-0 | `SeerRay-Lab/Xiaomi-OCR-0` | 1.77 | Native CPU/CUDA or DMR |

All selected files, revisions and hashes are in
[`parser-vlm-models.lock.json`](../../deployment/parser-vlm-models.lock.json).
Surya/Chandra outputs are decoded as layout HTML; Infinity as layout JSON;
TeleOCR uses layout detection followed by crop recognition; Xiaomi emits Markdown
and OTSL tables with page-level provenance. Model-generated HTML is never served
as a reader. Original PDF/page images, deterministic recovery and nonblocking
content checks continue through the shared IR adapter.

For the lightweight image, comment CPU and enable the DMR mode block in the local
Compose file. Set `PARSER_DMR_BACKEND=vllm` for a compatible Linux/WSL2 NVIDIA Docker
Model Runner, or `mlx` for an Apple Silicon vLLM Metal backend that supports the
selected architecture. `PARSER_DMR_URL` defaults to Docker's internal hostname; an
explicit local Docker-managed Runner such as `http://vllm-runner:12434` may be used.
It must provide the model-management, configuration and inference APIs.
Infinity's upstream SDK requires vLLM 0.26.0 or later. The optional translation
Runner's default 0.19.1 image does not meet that prerequisite; select a compatible
Docker-managed backend before preparing these parsers. Metal uses its own version
scheme and still needs architecture/image-inference verification.

```sh
docker compose build app parser db
docker compose up -d --wait
```

Select a compatible parser in Settings and use **准备解析模型** to finish large
downloads before starting a PDF. The parser's timeout includes first-use preparation.
Saving a default does not prepare it; a queued parse retains its selected profile.
The lightweight image can build for Linux amd64/arm64; it does not install native
inference frameworks. Native parser images retain their existing amd64 deployment.
Existing saved Paddle/Docling choices are preserved: select a DMR-compatible parser
when opting into DMR mode. TeleOCR needs custom vLLM registration upstream, so the
generic DMR image excludes it and keeps its native implementation.

Preparation streams verified files into DMR's OCI model store and rechecks the exact
content ID and effective configuration before sending a page image. The application
does not install inference engines or silently substitute models/backends. Model
architecture and image-input support must exist in the selected Docker engine.
This integration does not certify every hardware/model combination. See
[Docker inference engines](https://docs.docker.com/ai/model-runner/inference-engines/),
[Surya](https://github.com/datalab-to/surya), [Chandra](https://github.com/datalab-to/chandra),
[Infinity-Parser2](https://github.com/infly-ai/INF-MLLM/tree/main/Infinity-Parser2),
[TeleOCR](https://huggingface.co/XingChen-AGI/TeleOCR) and
[Xiaomi-OCR-0](https://huggingface.co/SeerRay-Lab/Xiaomi-OCR-0).

The native cache and DMR store each retain a copy. Allow about twice the download
size on disk for DMR preparation (about 141 GB for Pro), plus inference memory and
temporary space. Surya and Chandra weights have their upstream OpenRAIL terms;
the other added models declare Apache 2.0. The model catalogue records those terms.
No live new-model inference or ARM cold start is implied by offline regressions.

When upgrading an existing instance, merge the new cache volume, preparation service,
internal network and parser/app mounts into its ignored local Compose configuration.
Preserve its project name, image pins, mode, overrides and data volumes. A rebuild
alone cannot add mounts/services to an older local Compose file. Cached models are
re-downloadable runtime resources; library backups do not include model cache volumes.

## Docker-managed MLX

Apple MLX uses Docker Model Runner's macOS Metal backend; Linux containers cannot
access Metal directly. Provision the compatible [backend payload](mlx-backend.md)
and package the exact locked Paddle weights before enabling MLX mode in the local
Compose file.

Prepare Paddle in CPU mode through Settings first. Then create an empty
`MODEL_EXPORT_DIR` and make it writable by the exporter
container's UID 10001. An automatically created root-owned bind directory will not
work. The `model-export` service has no default output mount; supply it explicitly:

```sh
export MODEL_EXPORT_DIR=/absolute/path/to/empty-model-output
docker compose run --build --rm --volume "$MODEL_EXPORT_DIR:/export" model-export
docker model package --safetensors-dir "$MODEL_EXPORT_DIR/paddleocr-vl-1.6" --license "$MODEL_EXPORT_DIR/paddleocr-vl-1.6/LICENSE" local/paddleocr-vl-1.6:latest
docker model inspect docker.io/local/paddleocr-vl-1.6:latest
```

`PADDLE_MLX_MODEL` is the packaged reference, normally
`docker.io/local/paddleocr-vl-1.6:latest`. Set `PADDLE_MLX_MODEL_ID` to the actual
inspected content ID. After a real image request succeeds, set
`PARSER_MLX_VERIFIED_MODEL_ID` to that same ID. Keep these values in a local ignored
environment file; never invent a digest or reuse a receipt after replacing the model/backend.

Comment the current mode block and uncomment the entire MLX mode block, including
the top-level model declaration, in local `compose.yaml`. With those values saved
in `.env.mlx`, start the selected deployment:

```sh
docker compose --env-file .env.mlx up -d --build --wait
```

The parser rechecks backend/model metadata and sends region images to the fixed
Docker-managed `/engines/vllm/v1` route with no translation credentials. Its MLX
bridge permits backend access and is not a domain firewall. Only Paddle recognition
uses MLX; layout and other parser profiles remain CPU and report that fact.

The host model process has its own memory settings. Cancellation stops parser work
and prevents late commits; already submitted backend inference may still finish.
Changing Docker, the backend or model requires fresh image inference and a controlled
end-to-end PDF check. Static config, GPU arithmetic or a model-status message does
not provide that proof. This guide makes no claim about the current running instance.
