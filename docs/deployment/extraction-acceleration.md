# PDF extraction acceleration

New preferences default to PaddleOCR-VL-1.6. Saved preferences and queued jobs
retain their selected profile; legacy tasks without a profile keep their existing
Docling behavior. Settings lists only the runtimes reported by the deployed parser,
including unavailable reasons. A new job freezes its resolved model, device and
timeout instead of rereading preferences during execution.

| Deployment | Build/runtime | Paddle recognition and layout | Docling / Granite |
| --- | --- | --- | --- |
| CPU | Default parser image | CPU / CPU | CPU |
| CUDA | Unified CUDA image | CUDA / CUDA | CUDA; RapidOCR uses ONNX CPU |
| Apple MLX | CPU parser image plus Docker Model Runner | MLX / CPU | CPU |

CPU/CUDA images contain locked model assets and parse without network access.
The CUDA build uses separate Torch/Paddle environments because their native GPU
libraries conflict. They share the same parser code and model directory.

```sh
# CPU
docker compose -f deployment/compose.production.yaml up -d --build
# CUDA on a host with compatible NVIDIA driver and Docker GPU support
docker compose -f deployment/compose.production.yaml -f deployment/compose.cuda.yaml up -d --build
```

The parser handles one PDF at a time with bounded process resources, deadlines and
fence checks. Its 16 GiB cgroup ceiling does not allocate memory to Docker's VM
or constrain GPU VRAM. Runtime availability is not proof that a chosen PDF/model
fits in available memory. Failed device/model selection does not silently fall back.

## Docker-managed MLX

Apple MLX uses Docker Model Runner's macOS Metal backend; Linux containers cannot
access Metal directly. Provision the compatible [backend payload](mlx-backend.md)
and package the exact locked Paddle weights before enabling the overlay.

Create `MODEL_EXPORT_DIR` first and make it writable by the exporter container's
UID 10001. An automatically created root-owned bind directory will not work.

```sh
export MODEL_EXPORT_DIR=/absolute/path/to/empty-model-output
docker compose -f deployment/compose.model-package.yaml run --build --rm model_export
docker model package --safetensors-dir "$MODEL_EXPORT_DIR/paddleocr-vl-1.6" --license "$MODEL_EXPORT_DIR/paddleocr-vl-1.6/LICENSE" local/paddleocr-vl-1.6:latest
docker model inspect docker.io/local/paddleocr-vl-1.6:latest
```

`PADDLE_MLX_MODEL` is the packaged reference, normally
`docker.io/local/paddleocr-vl-1.6:latest`. Set `PADDLE_MLX_MODEL_ID` to the actual
inspected content ID. After a real image request succeeds, set
`PARSER_MLX_VERIFIED_MODEL_ID` to that same ID. Keep these values in a local ignored
environment file; never invent a digest or reuse a receipt after replacing the model/backend.

```sh
docker compose --env-file .env.mlx -f deployment/compose.production.yaml -f deployment/compose.mlx.yaml up -d --build
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
