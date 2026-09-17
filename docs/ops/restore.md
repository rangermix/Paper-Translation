# Backup, recovery and safe external dispatch

Run from the project root with Docker and Compose. The examples below use the
shared `deployment/compose.production.yaml`. If you deploy with an ignored local
`compose.yaml`, use that same configuration instead. Preserve the existing project
name, image pins, and deployment overrides when running maintenance commands.

Create and verify a backup:

```powershell
docker compose -f deployment/compose.production.yaml run --rm --no-deps maintenance python -m packages.maintenance backup
docker compose -f deployment/compose.production.yaml run --rm --no-deps maintenance python -m packages.maintenance verify-backup --backup-id BACKUP_ID
```

Replace `BACKUP_ID` with the identifier printed by the first command. A successful
backup includes a custom-format PostgreSQL dump and hashes of database-referenced
source PDFs, snapshots, completed parser evidence, publication files, exports and
upload chunks. Unreferenced temporary output is excluded. An incomplete backup
keeps a temporary directory and must not be restored. The maintenance service has
no Provider key. Backups themselves contain document text and should be protected
as private library data.

Maintenance obtains an exclusive advisory session lock after active workers
finish their bounded operations. It uses repeated nonblocking lock attempts, so
it does not prevent those workers from completing their short transactions on
other database connections. Once the lock is held, normal writes and new claims
stop. Backup and restore hold the lock across database and file operations.

Restore into the same explicitly selected Compose project's named volumes:

```powershell
docker compose -f deployment/compose.production.yaml run --rm --no-deps maintenance python -m packages.maintenance restore --backup-id BACKUP_ID --replace
docker compose -f deployment/compose.production.yaml run --rm --no-deps maintenance python -m packages.maintenance verify
```

`--replace` explicitly permits replacing nonempty `/data` and `/uploads` volumes
and restoring their database snapshot. The CLI refuses arbitrary host targets.
Manifest hashes are verified before replacement. Keep a separate verified backup
before replacing data. A failed command leaves maintenance enabled; inspect the
failure and rerun verification or restore a known-good backup before opening
writes. The command does not erase unrelated host directories.

Both successful backup and restore leave maintenance enabled and external
dispatch disabled. Inspect documents, original PDFs, publication pointers and any
`outcome_unknown` attempts, then reopen ordinary writes:

```powershell
docker compose -f deployment/compose.production.yaml run --rm --no-deps maintenance python -m packages.maintenance maintenance-off
```

External dispatch stays disabled. In Settings → AI 服务 → 外部 API 请求, select
“允许外部 API 请求” and save to allow dispatch again. This state persists in
PostgreSQL across container recreation and does not use an environment variable.
Provider configuration, external-processing confirmation and (when enabled) cost
controls still apply to each request. If unknown billing risk remains, review the
specific attempts, then check the risk acknowledgment and enter a reason on the
page. The maintenance CLI `enable-dispatch` remains available with the same risk
guard (`--accept-unknown-risk --reason "Reviewed the request evidence"`).
This records a manual risk acknowledgment while retaining every unknown permit
in the budget. It enables other approved jobs; it does not resume unknown tasks,
assert that a request was uncharged, or create Provider usage evidence. A specific
unknown task still needs its separate explicit risk-retry action.

Schema upgrades run numbered frozen SQL statements in
`packages/domain/migrations`, with recorded SHA-256 checksums. Future ORM changes
do not rewrite old migration definitions. Downgrades and changed installed
checksums are rejected. Pre-release databases created before checksums existed
retain NULL checksum provenance for those old steps; new steps are recorded.
Rollback uses the verified pre-upgrade database and content backup with its
matching image. It does not run destructive reverse migrations on live history.

`docker compose down` preserves named volumes; `down --volumes` deletes them and is
not an upgrade or backup procedure. The isolated acceptance harness
`.agent/harness/offline_compose_roundtrip.py` uses prepared acceptance images to
create fresh projects, dump PostgreSQL, restore into a second fresh project and
compare document and export bytes. It requires available acceptance ports and
must run alone because its ports and working output are shared. The former
production-targeted `backup_roundtrip.py` is retained only as
[historical source](../../.agent/notes/historical-probes/README.md). Neither historical
evidence nor this harness implies that every crash point or storage failure has
been tested.

## Upgrade the older bookworm instance into a fresh trixie project

The production default now pins PostgreSQL15-trixie. A pre-release installation
using PostgreSQL15-bookworm must move through a logical backup into a fresh
database volume so indexes/collations are created by the destination libraries.
Never replace the old PostgreSQL image against its existing volume as this
upgrade procedure. Keep the old instance and its volumes available for rollback.

1. Select the old Compose project explicitly and record its actual running image
   IDs with `docker compose -p OLD_PROJECT -f deployment/compose.production.yaml ps`
   and `docker inspect OLD_APP_CONTAINER OLD_DB_CONTAINER`. Do not run `up` on it
   with the new default. Preserve the matching old Compose configuration/images.
2. Use the maintenance image that matches that old schema to create and verify
   its backup. `docker compose ... run --no-deps maintenance` can use the old
   `APP_IMAGE` override without recreating existing services. Capture the printed
   backup identifier and the actual named backup volume from `docker inspect`.
   Backup leaves the old library in maintenance and disables external dispatch.
3. Prepare `deployment/restore-from-old.yaml` containing only the exact selected
   backup volume. This volume is shared; the database, data, uploads and internal
   configuration volumes must all be new in the new project:

   ```yaml
   volumes:
     backups:
       external: true
       name: OLD_PROJECT_backups
   ```

4. Start the new project on a different loopback port, using final pinned app and
   parser image references. Set `APP_IMAGE`, `PARSER_IMAGE` and `PORT` in the
   command environment, then run:

   ```powershell
   $env:PORT = '18080'
   docker compose -p NEW_PROJECT -f deployment/compose.production.yaml -f deployment/restore-from-old.yaml up -d --wait --no-build --pull never
   docker compose -p NEW_PROJECT -f deployment/compose.production.yaml -f deployment/restore-from-old.yaml run --rm --no-deps maintenance python -m packages.maintenance restore --backup-id BACKUP_ID
   docker compose -p NEW_PROJECT -f deployment/compose.production.yaml -f deployment/restore-from-old.yaml run --rm --no-deps maintenance python -m packages.maintenance migrate
   docker compose -p NEW_PROJECT -f deployment/compose.production.yaml -f deployment/restore-from-old.yaml run --rm --no-deps maintenance python -m packages.maintenance verify
   ```

   No `--replace` is needed: the selected destination data volumes are fresh.
   The destination schema is upgraded through frozen, additive migrations after
   the logical restore. Existing unknown attempts and their reserved risk are
   retained. The original project's database volume is never attached.
5. Verify the destination readiness and compare representative original-PDF,
   sealed snapshot, current/old publication and export hashes with the verified
   backup. Check unknown attempts and counters, then use `maintenance-off` in
   `NEW_PROJECT` for ordinary writes. External dispatch remains disabled until
   its separate review/authorization step. Keep clients on the old read-only
   instance until destination verification passes; then switch the chosen port.

The real acceptance implementation is `.agent/harness/offline_compose_roundtrip.py`:
both projects use fresh named volumes, outbound networks are disabled, and the
restore compares original bytes, library state, two legacy artifacts and four
worker exports. Its per-run command logs retain the actual image references.
