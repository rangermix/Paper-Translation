# Execution evidence and optional probes

Run from the repository root. The default regression workflow is documented in
[tests/README.md](../../tests/README.md). These tools supplement it with command
records, isolated deployment probes and explicitly authorized model tests.
There is no separate milestone catalog or generated project-completion gate.

## Command records

```sh
python .agent/harness/acceptance.py probe
python .agent/harness/acceptance.py fingerprint
python .agent/harness/acceptance.py run --id focused-tests --kind automated -- python -m pytest -q tests/unit
```

`run` records the arguments, source fingerprint, Git commit/dirty state, environment,
exit status, elapsed time and redacted output. Logs and records use unique names
under `.agent/tmp/evidence/`. A changed source tree makes the run fail. Optional
`--tests` values describe the checks exercised, not entries in a planned registry.
`--full-scenario` is an explicit scope claim and requires actual execution evidence;
static checks cannot claim it. Exit status zero alone does not certify the product.

`blocked` records a concrete missing prerequisite. `review` imports independent,
source-bound findings after file/hash verification; see [review format](AGENT_REVIEW.md).
Fake providers belong to automated evidence, never live-provider evidence. YAML
validation is a static check, never a Compose cold-start result.

Fingerprints include maintained source, tests, fixtures and harness code. They
exclude agent notes/memory/output, dependencies, local Compose/editor settings and
private configuration/secret files without reading their contents. Record selected
runtime configuration separately with redacted evidence. Archived source hashes
are not silently promoted after a path change.

## Explicit probes

Most matrix scripts accept candidate images or target a disposable Compose project.
Read their arguments and target configuration before running them. They can create
containers/volumes, execute native parsers or mutate test data. Historical source
review replays require their exact ignored evidence corpus; absence is not a pass.

- `verify_compose.py`: inspects `compose.example.yaml` by default and supports
  CPU/CUDA/MLX configurations, including MLX model bindings. Select another input
  with `--file`; `--running` inspects that deployment and requires `--project-name`.
- `offline_compose_roundtrip.py`: fresh-project backup/restore exercise, using
  root `compose.example.yaml`, prepared candidate images and overrides generated
  inside its unique run directory. It does not use the local production configuration.
- `release_inventory.py`: combines exact image IDs with matching scan/SBOM output
  into a fresh report. Use `--help` for candidate arguments.
- `parser_runtime_dependencies.py`: checks actual dependencies/model assets inside
  the selected parser image. This is inventory, not inference or a vulnerability audit.
- `build_*fixtures.py`: explicit synthetic-fixture generators; not application code.
- `live_provider_run.py`: guarded real-model runner requiring the authorization
  described in [LIVE_PROVIDER.md](LIVE_PROVIDER.md).

To inspect an existing local instance, replace `EXISTING_PROJECT` with its actual
Compose project name and use the same configuration inputs as its deployment:

```sh
python .agent/harness/verify_compose.py --file compose.yaml --project-name EXISTING_PROJECT --running
```

Add `--env-file .env.mlx` when that is the instance's interpolation file. Both
`--file` and `--env-file` may be repeated in deployment order for local overrides.
This checks configuration and container state; it does not execute model inference.

Dated source probes under `../notes/historical-probes/` are archival, not current
entry points. Keep credentials, persistent disks, old receipts and evidence intact.

The sole tracked Compose template includes `checks`, `tests`, `model-tools` and
`local-translation` profiles. Use explicit service targets for one-off runs; profile
`up` also starts default product services. Routine tests/checks must retain their
separate project names and `-f compose.example.yaml` options from the test guide.
