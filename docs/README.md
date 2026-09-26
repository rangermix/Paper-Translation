# Documentation

These guides describe maintained source and commands. Deployment-specific results
belong in run evidence; an old test report does not describe a running instance.

| Guide | Contents |
| --- | --- |
| [Product scope](product-baseline.md) | Implemented capabilities and boundaries |
| [Architecture](architecture.md) | Processes, storage, immutable revisions and isolation |
| [Workflows](workflows.md) | Translation, recovery, original-only content and task history |
| [API](api.md) | Current route groups, schemas, concurrency and request handling |
| [Deployment](deployment/README.md) | Compose setup, file ownership and configuration |
| [Extraction acceleration](deployment/extraction-acceleration.md) | CPU, CUDA and Docker-managed MLX |
| [MLX backend](deployment/mlx-backend.md) | Build, installation and verification procedure |
| [Local translation](deployment/local-translation.md) | On-demand models and shared MLX backend |
| [Backup and restore](ops/restore.md) | Maintenance lock, backups and upgrades |
| [Retention](ops/retention.md) | Cleanup policy and bounded maintenance commands |
| [Dependencies](ops/dependencies.md) | Locks, packaged models and image inventories |
| [Tests](../tests/README.md) | Reproducible checks and test evidence limits |
| [Resources](../res/README.md) | Runtime resources and controlled seed provenance |

Completed milestone plans, obsolete acceptance registries and superseded designs
are available in Git history. Current implementation is defined by source,
runtime schemas and tests, without a parallel backlog claiming it is unimplemented.

Active feature work: [translation consistency specification](plans/2026-09-26-translation-consistency-design.md),
[options and runtime cost](plans/translation-consistency-options.md), and
[implementation plan](plans/2026-09-26-translation-consistency.md). These documents
separate the delivery scope from optional research integrations.
