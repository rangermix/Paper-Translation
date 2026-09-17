# Deployment file inventory

Deployment inputs live in [`deployment/`](../../deployment/) and Docker recipes
in [`deployment/images/`](../../deployment/images/). The root `compose.yaml` is
local and ignored; `compose.example.yaml` is the portable standalone template.

The repository layout review retained these distinct build/runtime/test inputs:

| Input | Why it remains |
| --- | --- |
| `compose.production.yaml` | Shared production service, volume and isolation definitions |
| `compose.cuda.yaml` | NVIDIA device configuration and CUDA build selection |
| `compose.mlx.yaml` | Docker Model Runner model binding and parser inference network |
| `compose.local-translation.yaml` | Optional on-demand local model preparation service |
| `compose.model-package.yaml` | Offline export of verified parser weights for Docker model packaging |
| `compose.acceptance-offline.yaml` | Dedicated offline acceptance overrides and harness mounts |
| `compose.test.yaml` | Isolated Linux/PostgreSQL test environment |
| `compose.verify.yaml` | Network-isolated repository contract checks |
| `images/` | App, parser, database, test and verifier image recipes |
| `cuda/`, `cuda-paddle/` | Separate pinned environments for incompatible Torch/Paddle native dependencies |
| `mlx-backend/` | Docker-built macOS backend payload and extraction/initialization helpers |
| `local-translation-backend/` | Translation support layered onto the shared MLX backend |
| `parser-models.lock.json` | Immutable revision, size and hash allowlist for bundled parser weights |
| `provider-profile.json`, `provider_key.empty` | Empty fallback configuration allowing startup without a provider |

Two redundant/outdated files were removed: the design-only
`dependency-inventory.json` checklist and `production.env.example`. Release image
override examples now live in [`.env.example`](../../.env.example). Real dependency
evidence comes from lockfiles and actual image inventories, as described in
[dependency evidence](../ops/dependencies.md).

See the [Compose contract](compose-contract.md), [deployment procedure](../ops/deploy.md),
[acceleration guide](extraction-acceleration.md), [MLX backend procedure](mlx-backend.md)
and [local translation guide](local-translation.md). The dated
[local translation validation](local-translation-validation.md) and
[parser repair](job-failure-repair-20260915.md) describe their recorded runs.
