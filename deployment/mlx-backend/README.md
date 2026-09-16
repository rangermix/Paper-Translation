# Docker-managed MLX backend payload

This document records the 2026-09-13 Paddle backend build and its installation
on the test Mac. Later shared parser/translation backend work is documented in
[local translation](../local-translation.md) and [the parser repair](../job-failure-repair-20260915.md).
The recorded image and paths below are historical setup evidence; inspect the
selected deployment before reusing them or replacing an installed backend.

The 2026-09-13 repair uses the floating image tag
`local/paper-translation-vllm-metal:latest`. It is a local, custom `darwin/arm64`
OCI backend payload built with Docker, loaded into Docker's image store, and
extracted into Docker Model Runner's existing backend directory. DMR launches
and manages the model process; this does not install a separate Python server.

Docker's published `vllm-metal-v0.2.0-20260420-142150` package fails Paddle image
preprocessing and skips the vision encoder. The custom payload uses upstream
vLLM 0.29.0 and vLLM Metal 0.29.0, whose matching wheels support Paddle vision.
The tested dependency set includes MLX 0.32.1, mlx-vlm 0.6.17 and Transformers
5.17.0. The package versions are intentional compatibility constraints; the
output image reference floats. Rebuilding it requires fresh inference proof.

## Build

Run from the repository root on Apple Silicon. Start with Docker Model Runner's
self-contained macOS Python 3.12 runtime already provisioned by Docker. Copy its
interpreter/standard library, excluding the old third-party dependencies:

```sh
TASK_DIR=".agent/tmp/mlx-backend-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$TASK_DIR/runtime"
cp deployment/mlx-backend/{Dockerfile,requirements.in,sitecustomize.py} "$TASK_DIR/"
rsync -a --exclude site-packages --exclude __pycache__ --exclude prebuilt \
  --exclude .vllm-metal-version \
  "$HOME/.docker/model-runner/vllm-metal/" "$TASK_DIR/runtime/"
codesign --force --sign - --options 0 "$TASK_DIR/runtime/bin/python3"
docker buildx build --platform darwin/arm64 --progress plain \
  --output "type=oci,dest=$TASK_DIR/backend.oci.tar" \
  -t local/paper-translation-vllm-metal:latest "$TASK_DIR"
docker load --input "$TASK_DIR/backend.oci.tar"
python3 deployment/mlx-backend/extract_oci.py \
  "$TASK_DIR/backend.oci.tar" "$TASK_DIR/extracted"
```

The signature change applies only to the copied custom interpreter. Its
original Docker signature enables library validation, which rejects the new
upstream native wheels because their signing teams differ. The original
Docker runtime and global macOS security settings are preserved.

All dependency installation occurs during Docker build. Cross-platform wheel
resolution selects macOS ARM64 libraries; the pinned pure-Python mlx-lm git
dependency builds in the build stage. There is no runtime pip or model download.
The final scratch image is a macOS payload, not a runnable Linux container.

`sitecustomize.py` sets offline mode and a 0.25 MLX memory fraction for this
16 GiB M4 host. DMR 1.2's Metal adapter ignores its structured GPU memory
utilization option. The native setting was verified in the actual engine log:
3.18 GB usable Metal allocation and a 0.80 GB KV budget. This is a fraction of
Metal's recommended working set, not a hard cap on total process RAM.

## Install and verify

Stop new parser work and wait for active parses to finish. Clear
`PARSER_MLX_VERIFIED_MODEL_ID` before replacing a backend. Unload this project's
model using `docker model unload MODEL_ID`; do not unload unrelated models.
Preserve the existing `~/.docker/model-runner/vllm-metal` directory in a new
`.agent/local-data/` backup directory, then move the verified extracted
`vllm-metal` directory into that same DMR location. Never overlay old and new
site-packages. The payload's `dev` marker is an existing DMR development-package
mechanism that prevents replacement with Docker's older package.

After installation, test native MLX GPU execution, real image requests through
the Compose parser and `/engines/vllm/v1/chat/completions`, then a complete
controlled PDF job. Only after successful image inference set
`PARSER_MLX_VERIFIED_MODEL_ID` to the actual packaged model ID. Keep the resolved
backend image ID, model ID, commands and outputs with the setup evidence.

DMR caches the version text shown by `docker model status`; after a directory
replacement it may still display the old version while the engine logs and
responses show 0.29.0. The API has no reliable read-only package fingerprint.
The parser checks that a Metal backend is running and the correct model exists,
but its receipt is a setup attestation. Clear and refresh it after any model or
backend replacement, restore, or Docker upgrade. Do not infer vision support
from model metadata or status text alone.

## Historical installation and rollback procedure

The backend image ID recorded on 2026-09-13 was
`sha256:fa452affcb8fb570645938b0544b3150ce61628e0e9be5c4646478f804c135f4`.
The exact OCI archive is
`.agent/local-data/mlx-repair-20260913/backend-r4.oci.tar`;
the original Docker runtime is preserved at
`.agent/local-data/mlx-repair-20260913/docker-original`.
That run's Compose values were stored in
`.agent/local-data/mlx-docker-20260913/mlx.env`.

That run recreated its parser with the following command. Current deployments
must preserve their own project, image pins and optional translation overrides:

```sh
docker compose --env-file .agent/local-data/mlx-docker-20260913/mlx.env \
  -f deployment/compose.production.yaml -f deployment/compose.mlx.yaml \
  up -d --no-deps --no-build --wait parser
```

To roll back, first clear the receipt and wait for active parsing to finish.
Recreate only the parser with the base production Compose file to restore CPU
routing. Unload this model, preserve the custom runtime in a new local-data
directory, and move `docker-original` back to the DMR backend path. Do not remove
the model store, application volumes or historical evidence. CPU Paddle still
has the previously observed Docker VM memory constraint; restoring CPU routing
does not establish that it can load Paddle on this Mac.

Evidence: `.agent/tmp/mlx-repair-20260913T125316Z/verification.md`.
Upstream references: [vLLM Metal 0.29.0](https://github.com/vllm-project/vllm-metal/releases/tag/v0.29.0),
[vLLM 0.29.0](https://github.com/vllm-project/vllm/releases/tag/v0.29.0),
[DMR Metal backend implementation](https://github.com/docker/model-runner/blob/main/pkg/inference/backends/vllm/vllm_metal.go).
