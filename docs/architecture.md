# Architecture

The application consists of an HTTP app, a durable worker, an isolated PDF parser
and PostgreSQL. Compose also provides volume initialization, migrations and an
explicit maintenance service. The optional local translation service shares the
Docker-managed MLX backend. See the [single Compose template](../compose.example.yaml);
each deployed instance uses its preserved local `compose.yaml`.

## Source and process boundaries

| Path | Responsibility |
| --- | --- |
| `src/apps/api/` | Strict request models, API routes, frontend and artifact responses |
| `src/apps/web/` | React management UI |
| `src/packages/` | Domain, queue, providers, billing, parser adapters, publishing and maintenance |
| `src/workers/main.py` | Persistent queue dispatch and validated result commits |
| `src/workers/parser/` | Bounded PDF child processes and spool protocol |
| `res/` | Runtime IR schema and controlled reader/seed resources |

The worker copies an authorized PDF into a task/fence-specific parser input
directory. Requests contain generated storage keys, source hash, selected parser
and deadline. The parser reads only its input volume and writes results and
evidence to its output volume; it has no database or translation credentials.
The worker revalidates paths, hashes, task identity and lease fence before committing.
CPU/CUDA parsing is network-isolated; MLX reaches Docker Model Runner on a dedicated
bridge. This bridge is not a domain firewall.

## Durable state

Database models live in [domain/models.py](../src/packages/domain/models.py).
The current migration sequence ends at 13 in
[domain/migrations](../src/packages/domain/migrations). Installed migration bytes
and checksums are immutable; upgrades append migrations.

Original PDF assets, source revisions, translation revisions, editions and artifacts
have distinct identities. Source corrections create new revisions. Translation
snapshots bind the source and locale; artifacts bind those snapshots and a template.
Changing a template does not call a translation model. Existing artifacts are
served from their manifest; unpublishing clears the current pointer, while document
deletion prevents reads of its retained artifacts.

Workers claim tasks in short transactions, renew leases and fence late commits.
Mutable entities use generation/ETag checks; publication builds and verifies files
before a compare-and-swap pointer change. Deletion tombstones block late writes and
online reads. Pausing prevents new dispatch permits but cannot revoke requests
already sent.

## IR and readers

[document-ir.schema.json](../res/schemas/document-ir.schema.json) validates the
internal render input. [ir/validator.py](../src/packages/ir/validator.py) additionally
checks block ownership, reading order, source hashes, PDF coordinates, safe inline
content, protected references and resource paths. The IR is not a public upload format.

The stored `schema_version` and registered reader template IDs identify actual
persisted formats. They do not identify project releases. Preserve them when
reading old revisions or rebuilding a historical template. Frozen CSS/JavaScript
hashes are enforced by the [template registry](../src/packages/templates/registry.py).

Models return constrained translation content; they cannot supply HTML, filenames,
new source text or arbitrary links. Publication escapes text and only renders
validated structures. Original-only and fallback results remain distinguishable
from translated and human-reviewed content.

## Storage and secrets

Named volumes separate document data, upload staging, parser input/output,
PostgreSQL, internal service configuration, provider settings and backups.
The app resolves only registered PDF/artifact/export paths; it does not expose a
directory listing of the data volume.

Provider settings and keys use versioned backend files with an atomic current
pointer. The app can save them; workers read the selected revision. The parser,
database and maintenance service do not receive that key store. Standard backups
exclude provider configuration, so a new host must configure it again.

Backup, restore and retention share an exclusive PostgreSQL advisory lock.
They leave maintenance enabled and external dispatch disabled until separately
reviewed. See [backup and restore](ops/restore.md).
