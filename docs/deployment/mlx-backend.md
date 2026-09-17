# Docker-managed MLX backend payload

The repository builds a custom `darwin/arm64` payload for Docker Model Runner on
Apple Silicon. DMR starts and manages it; the application does not install or start
a separate host Python server. The final scratch image is a macOS payload, not a
runnable Linux container. Pinned backend dependencies are in
[`requirements.in`](../../deployment/mlx-backend/requirements.in).

## Build

Start with Docker Model Runner's provisioned macOS Python runtime. Copy it into a
fresh build directory, excluding existing third-party libraries:

```sh
TASK_DIR=".agent/tmp/mlx-backend-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$TASK_DIR/runtime"
cp deployment/mlx-backend/{Dockerfile,requirements.in,sitecustomize.py} "$TASK_DIR/"
rsync -a --exclude site-packages --exclude __pycache__ --exclude prebuilt --exclude .vllm-metal-version "$HOME/.docker/model-runner/vllm-metal/" "$TASK_DIR/runtime/"
codesign --force --sign - --options 0 "$TASK_DIR/runtime/bin/python3"
docker buildx build --platform darwin/arm64 --progress plain --output "type=oci,dest=$TASK_DIR/backend.oci.tar" -t local/paper-translation-vllm-metal:latest "$TASK_DIR"
docker load --input "$TASK_DIR/backend.oci.tar"
python3 deployment/mlx-backend/extract_oci.py "$TASK_DIR/backend.oci.tar" "$TASK_DIR/extracted"
```

The signature change affects only the copied interpreter, allowing the payload's
native wheels to load together. All dependency installation happens during image
build. The original Docker runtime and global macOS security settings are preserved.
The [`sitecustomize.py`](../../deployment/mlx-backend/sitecustomize.py) initializer
sets offline behavior and the backend's MLX memory policy; inspect it before choosing
host memory settings. Memory fractions are not a hard cap on total process RAM.

## Install and validate

Stop new parser/translation work and wait for active inference. Clear the parser's
MLX verification receipt. Unload only this project's idle model, and back up the
entire existing `~/.docker/model-runner/vllm-metal` directory into a new persistent
`.agent/local-data/` directory. Replace the backend directory with the extracted
payload rather than overlaying old and new packages.

Check the actual engine logs, a real image request through the Compose parser, and
a controlled PDF job. Only after successful image inference restore
`PARSER_MLX_VERIFIED_MODEL_ID` using the actual packaged model ID. Record the source,
backend image/model IDs and outputs. Status text alone is insufficient because DMR
can retain a cached version label after a payload replacement.

Install the [translation extension](local-translation.md) before the final checks
when using local translation. Every replacement, Docker upgrade or restore requires
fresh proof. The runtime heartbeat checks model/backend availability; it does not
reproduce the installation's inference check.

## Rollback

Keep the exact prior payload and local Compose settings. Stop new work, wait for
inference, clear the receipt, unload only the affected model and restore the saved
backend directory. Preserve application volumes and model caches. Verify the restored
backend before enabling work. Switching to CPU routing requires enough Docker VM
memory and its own extraction check; it is not automatic fallback.
