# Full workspace deployment · 2026-09-16

The user requested rebuilding and deploying all current workspace changes,
superseding the earlier theme-only deployment preparation. The complete current
app, parser and PostgreSQL images were built through Docker Compose and deployed
to http://127.0.0.1:8080. The database was upgraded from schema 12 to 13.

## Source and deployed images

The build includes the existing uncommitted parser/environment changes, the
committed task-history changes, and Automatic theme from `037f50c`. This is a
workspace build, not a clean checkout of that commit. Existing worktree changes
remain intact. The recorded 297-file build-input snapshot has SHA-256
`80901118087e2448ea9565ddcf185bebd34ebc8f556848271c4165a628e622fc`.

| Services | Image ID |
|---|---|
| app, worker, local-translator | `sha256:707a96b2fada4233e543b6e48563691e6636b510327f981708ec76a83bb01b9b` |
| parser | `sha256:67ae05effd13f2545fbaf7d6f0a5344833ed325daf11de8c11825091d223e016` |
| db | `sha256:2813916ca4a16bbddf60dcc2f0f4cf33618f35cfb3afe79c798d9e20da74285f` |

Each image has the `full-20260916-037f50c` tag; the three `:local` aliases now
point to the deployed images. Previous app/parser/db images remain tagged
`before-full-20260916`.

The existing Docker Model Runner backend and packaged Paddle model were retained.
Its active translation startup file matches the workspace, and the installed
MLX customization includes the workspace base customization and translation
bootstrap. No host inference service or runtime dependency installation was added.

## Verification

- Docker builds passed for all three images, including pinned parser model downloads.
- 585 backend unit/integration checks passed against isolated PostgreSQL; two
  existing dependency deprecation warnings were reported.
- 22 browser regression checks passed for history clearing, parser settings,
  task presentation and logs. The prior theme checkpoint passed 18 frontend
  unit tests and desktop/mobile theme checks.
- Automatic defaults and Light/Dark/Automatic persistence passed against real
  PostgreSQL, including a new app instance reading the saved selection.
- Production browser checks passed at 1440×1060 and 390×844: Automatic follows
  system changes, the history dialog opens and cancels, no browser errors, and
  no server writes. Automatic was simulated only in the browser for this check;
  the existing saved Dark selection was preserved.
- Two actual Paddle image requests through Docker-managed MLX returned the
  expected text. Controlled HTTP → PostgreSQL → worker → parser → MLX PDF job
  `job_0df8c758c17245f8a0e60a523536ba50` succeeded in 57.81 seconds, recorded MLX
  recognition/CPU layout, and preserved the original PDF. Only the disposable
  verification document was deleted afterward.
- All five services are healthy. Readiness reports schema 13 and seven verified
  stored objects. Preferences, public Provider configuration and pre-existing
  migration checksums were preserved. New maintenance audit records are expected.
- Maintenance is off; external dispatch is restored to its original enabled
  state; unknown/inflight requests and active jobs are zero. No paid Provider
  calls were made. This deployment does not establish CUDA inference support.

## Backup, operation and evidence

Verified pre-upgrade backup: `backup_855628421e1e4d5f91cde008c94753d5`, with 144
files, retained in the existing backup volume and reverified after the upgrade.
Existing volumes and service environment values were preserved. Image rollback
alone is not a schema downgrade; a full rollback must account for schema 13.

Use `.agent/local-data/full-deploy-20260916-01/compose.sh` for this release. It
combines the existing MLX configuration with the release image pins and the
production, MLX and local-translation Compose files.

Evidence: `.agent/tmp/full-deploy-20260916-01/`, especially
`deployment-result.json`, `source-manifest.json`, `rollout.log`, `pytest.xml`,
`live-ui.json`, `mlx-image-probe.log`, and `extraction/`. The earlier backup
receipt is in `.agent/tmp/theme-deploy-20260916-01/backup.log`.
Initial verification-script failures (test schema naming, history-button label,
and treating maintenance audit additions as unexpected record changes) are
retained alongside corrected successful checks. No production code changes were
needed to resolve them. Temporary QA containers/network and the preview server
were stopped.
