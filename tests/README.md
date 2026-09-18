# Running repository tests

Run from the repository root. The default suite uses test doubles for Providers;
it does not grant real model, credential or outbound-content authorization.

## Repository checks

```sh
docker compose -p paper-checks -f compose.example.yaml run --build --rm checks
```

This reuses the locked test image with no network, database dependency or product
volume. It checks actual runtime schemas/templates, test fixture integrity and
current documentation links. It does not evaluate an obsolete milestone registry.
On a supported locked development environment the equivalent command is
`uv run python src/tools/check_package.py`.

Synthetic PDF/IR inputs live under [fixtures/](fixtures/README.md), separate from
runtime [resources](../res/README.md). Both test profiles live in the sole tracked
[`compose.example.yaml`](../compose.example.yaml). The optional offline harness
creates its own temporary overrides and fresh projects for backup/restore probes.

## Reproducible Linux and PostgreSQL suite

Only Docker and Compose are needed. This test project has its own temporary
PostgreSQL database, test credentials and a memory-bounded Linux test container.
The image builds the frontend for real readiness checks and installs locked test
dependencies during the build:

```sh
docker compose -p paper-tests -f compose.example.yaml run --build --rm tests
docker compose -p paper-tests -f compose.example.yaml --profile tests down --volumes
```

`tests` starts only its dedicated `test-db` dependency. Port 55439 must be free;
set `TEST_DB_PORT` to another free port if needed. Keep that value for every command
in the test project. The separate test bridge exposes only this loopback-bound
database port for host tests; it shares no product network or volume.
Use the explicit project and template options above, rather
than the local production `compose.yaml`. A profile-wide `up` also starts default
product services; target `tests` with `run` instead. Cleanup must include
`--profile tests` so Compose removes the test database. Use `down --volumes` only
for this disposable test project, with the same `-p` and `-f` options.

Database fixtures create and drop a unique schema per test; they never reset the
product database. Runtime test containers install no packages and load no parser
model weights. The harness and relocation manifest are mounted read-only; private
agent state is excluded from the image.

The `parser_container` marker covers tests that actually execute the native PDF
inspection child. The production cgroup memory guard remains active. These tests
skip on hosts without a finite Linux container limit of at most 16 GiB, and run
in the container above. This is native inspection proof, not model inference or
full parser certification.

## Host development

On a supported Linux/Windows Python environment, install locked development
dependencies with `uv sync --frozen`. Start only the dedicated database:

```sh
docker compose -p paper-tests -f compose.example.yaml up -d --wait test-db
```

Then set `TEST_DATABASE_URL` to
`postgresql+psycopg://library_test:library_test_only@127.0.0.1:55439/library_test`
and run `uv run pytest -q -rs`; substitute `TEST_DB_PORT` if changed. Remove the
disposable test project afterward with the same cleanup command above. Pytest adds
`src/` to the import path. For other host Python module commands, set
`PYTHONPATH=src`. Without the database variable
PostgreSQL cases skip.
On macOS, use the Linux test container for the locked environment and real child
resource-limit test. Frontend unit/build checks are:

```sh
npm --prefix src/apps/web ci
npm --prefix src/apps/web test
npm --prefix src/apps/web run build
```

See [browser tests](browser/README.md) for the local preview, evidence-dependent
tests and explicit opt-in for tests that mutate an actual disposable application.

## Historical evidence

Some acceptance tests replay archived parser output or independent human review
under ignored `.agent/tmp/evidence/`. They skip when their recorded input is
absent; `-rs` reports the reason. The semantic-resolution publication replay is
marked `historical_evidence`. Supplying a partial/corrupt corpus remains a failure.
Do not replace missing independent review with fabricated fixtures or count a
skip as current acceptance. Ordinary authored fixture tests run separately.
