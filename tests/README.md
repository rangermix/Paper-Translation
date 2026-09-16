# Running repository tests

Run from the repository root. The default suite uses test doubles for Providers;
it does not grant real model, credential or outbound-content authorization.

## Reproducible Linux and PostgreSQL suite

Only Docker and Compose are needed. This test project has its own temporary
PostgreSQL database, test credentials and a memory-bounded Linux test container.
The image builds the frontend for real readiness checks and installs locked test
dependencies during the build:

```sh
docker compose -p paper-tests -f deployment/compose.test.yaml --profile tests run --build --rm tests
docker compose -p paper-tests -f deployment/compose.test.yaml down --volumes
```

Port 55439 must be free. Use a distinct project name and never merge this Compose
file into production. Database fixtures create and drop a unique schema per test;
they never reset the product database. Runtime test containers install no packages
and load no parser model weights. The harness and relocation manifest are mounted
read-only; private agent state is excluded from the image.

The `parser_container` marker covers tests that actually execute the native PDF
inspection child. The production cgroup memory guard remains active. These tests
skip on hosts without a finite Linux container limit of at most 16 GiB, and run
in the container above. This is native inspection proof, not model inference or
full parser certification.

## Host development

On a supported Linux/Windows Python environment, install locked development
dependencies with `uv sync --frozen`. Start only the dedicated database, then set
`TEST_DATABASE_URL` to
`postgresql+psycopg://library_test:library_test_only@127.0.0.1:55439/library_test`
and run `uv run pytest -q -rs`. Without this variable PostgreSQL cases skip.
On macOS, use the Linux test container for the locked environment and real child
resource-limit test. Frontend unit/build checks are:

```sh
npm --prefix apps/web ci
npm --prefix apps/web test
npm --prefix apps/web run build
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
