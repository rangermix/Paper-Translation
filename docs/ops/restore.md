# Backup, restore and upgrades

Run from the repository root using the instance's ignored local `compose.yaml`.
Keep the same project name, environment file, enabled profiles and any local
overrides used to start that instance. Add those same Compose options to each
command below; do not substitute the shared template for the instance's settings.

## Back up and verify

```sh
docker compose run --rm --no-deps maintenance python -m packages.maintenance backup
docker compose run --rm --no-deps maintenance python -m packages.maintenance verify-backup --backup-id BACKUP_ID
```

Replace `BACKUP_ID` with the printed identifier. A backup includes a PostgreSQL
custom-format dump and hashes of registered document files, source/translation
snapshots, parser evidence, artifacts, exports and upload chunks. Unreferenced
scratch output is excluded. An incomplete temporary backup is not restorable.
Provider configuration and API secrets are excluded and must be configured on a new
host. Backups contain private document content.

The maintenance service obtains the exclusive PostgreSQL advisory lock after
bounded active operations finish. This stops new claims and ordinary writes while
copying database and file state. Backup, restore and retention use the same lock.

## Restore

```sh
docker compose run --rm --no-deps maintenance python -m packages.maintenance restore --backup-id BACKUP_ID --replace
docker compose run --rm --no-deps maintenance python -m packages.maintenance verify
```

`--replace` explicitly permits replacement of nonempty managed data/upload volumes
and the database snapshot. Verify a separate backup before using it. The CLI checks
manifest hashes first and refuses arbitrary host targets. Without `--replace`,
restore requires fresh destination content volumes. Failure leaves maintenance on.

Successful backup and restore also leave maintenance on and external dispatch off.
Inspect documents, original PDFs, publication pointers and uncertain attempts, then:

```sh
docker compose run --rm --no-deps maintenance python -m packages.maintenance maintenance-off
```

This reopens ordinary writes only. Enable model dispatch separately in Settings.
Unknown requests retain their accounting risk; acknowledgment does not prove a
request was free or automatically resume it. Retrying an unknown task requires its
own explicit risk action.

## Schema, database and host changes

Numbered SQL migrations in
[`src/packages/domain/migrations/`](../../src/packages/domain/migrations/) are frozen
and checksum checked. New steps are additive; downgrades and changed installed
checksums are rejected. Rollback restores a verified backup with its matching image.

For a database major-version or base-distribution change, restore a logical backup
into a fresh project's database volume. In particular, an existing PostgreSQL 15
Bookworm volume must not be attached directly to the current Trixie-based image.
Keep the old project and images for rollback; share only the explicitly selected
backup volume with the new project. Start the new instance on a different loopback
port, restore, run `migrate` and `verify`, then inspect data and artifact hashes
before switching clients. Current and old application images must be compatible
with the schema they operate on.

`docker compose down` preserves named volumes. `down --volumes` deletes them and is
not a backup or upgrade procedure. Disposable restore tests must use their own
project, ports and volumes. The optional offline harness in
[`.agent/harness/offline_compose_roundtrip.py`](../../.agent/harness/offline_compose_roundtrip.py)
uses [`compose.example.yaml`](../../compose.example.yaml) with generated overrides
inside its own unique run directory. Read its explicit candidate/image requirements
before running it; its disposable projects are separate from the local instance.
