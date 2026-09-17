# Candidate build evidence

Use the actual source commit/tree fingerprint and explicit image tags when building
a candidate. The supported product recipes are `deployment/images/app.Dockerfile`,
`parser.Dockerfile` and `database.Dockerfile`. Shared Compose binds their build args
through `SOURCE_COMMIT` and `SOURCE_TREE_SHA256`; existing deployments may pin their
own images and overrides.

Run regression checks through `tests/compose.yaml` first. Record build commands,
architecture, dependency/model locks and actual image IDs in a fresh `.agent/tmp/`
directory. `acceptance.py run --kind compose` can capture command evidence; do not
label a build alone as successful startup or inference.

Exercise candidates on a disposable Compose project with fresh volumes. Verify
readiness, PDF processing with the selected model/device, publication/export and
backup/restore. Real provider calls need separate budget/content authorization.
No current guide authorizes replacing an existing production instance merely to
complete a release report. See [deployment](../../docs/deployment/README.md) and
[dependency evidence](../../docs/ops/dependencies.md).
