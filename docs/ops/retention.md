# Retention and orphan cleanup

Retention uses the production Compose maintenance service. It produces a plan by default; an explicit `--apply` executes a newly calculated plan while holding the same exclusive advisory lock as backup and restore.

Run from the repository root using the instance's local `compose.yaml`. Keep its
project name, environment file, enabled profiles and any local overrides; add the
same Compose options to the examples below. Do not substitute the shared template
for the selected instance's configuration.

```powershell
docker compose run --rm --no-deps maintenance python -m packages.maintenance retention
docker compose run --rm --no-deps maintenance python -m packages.maintenance retention --apply
```

The plan contains relative storage keys, reasons, file sizes and filesystem identity checks, an overall plan hash, expired upload and idempotency identifiers, and any skipped-link/missing-volume warnings. It does not print document bodies, receipt responses, database passwords, or Provider secrets. The default limit is 1,000 files and up to 1,000 records in each cleanup category; the scanner stops after 100,000 directory entries. Use `--limit` from 1 to 10,000 to change the per-run bound. If `truncated` is true, inspect the output and repeat until the remaining eligible work is drained. A dry-run plan is evidence, not a portable deletion script; apply computes references again under the lock.

| Content | Retention rule |
| --- | --- |
| Upload bytes | Upload expiry is 24 hours after creation. An expired upload is marked invalid before removing its temporary bytes. An active inspector task protects its upload even after the expiry timestamp. |
| Idempotency receipts | The API records a seven-day expiry. Cleanup removes only receipts whose stored expiry has passed. Job/attempt/fence records are not removed by this command. |
| Unreferenced staging, artifacts, parser copies and exports | Files older than 24 hours may be removed only when they have no database reference and are outside protected registered directories. |
| Parser input/output spool | Older-than-24-hour files for inactive tasks may be removed. Every fence of a resumable/active task and a recently reported active parser task remains protected. Missing parser volumes produce an explicit warning and no spool-cleanup claim. |
| Completed backups | Product backup directories expire after 30 days from their recorded creation time. Their manifest remains until the final bounded deletion pass, so another pass can still prove the original expiry. |
| Incomplete backup staging | Product-named temporary backup files older than 24 hours may be removed. Unrecognized directories and malformed completed-backup manifests are preserved for inspection. |

Every registered Artifact directory remains protected, including historical, preview and legacy versions that are not current. Registered exports protect their whole directory, including draft-export snapshots. Current and historical source snapshots, their assets and completed parser-evidence directories remain referenced. This command never deletes translation memories, including explicitly independent entries, and does not change publication pointers or reviewed translations. The separate document-deletion job handles tombstoned content and shared-asset references; retention cannot make a deleted document readable again.

Cleanup checks the current connection's exclusive PostgreSQL advisory lock and that maintenance and dispatch-disable flags are set. Backup and restore use the same lock, preventing file-copy/cleanup races. Files are checked for safe relative paths, resolved containment and matching filesystem identity immediately before deletion. Symbolic links and Windows junctions are never followed; no shell-composed recursive deletion is used. If an apply run fails partway, already expired input remains invalid and the remaining bytes can be inspected and cleaned in a later run.

Maintenance remains enabled and external dispatch remains disabled afterward. Inspect the plan and any warnings, then use `maintenance-off` to reopen ordinary writes. Enabling paid dispatch is a separate explicitly authorized action. Expiration of a local backup does not recall already downloaded copies or backups stored elsewhere.

Behavior is exercised by `tests/integration/test_retention.py` using an isolated
PostgreSQL database. Running those tests does not apply cleanup to a live library.
