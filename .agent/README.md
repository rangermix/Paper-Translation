# Agent workspace

Run commands from the repository root. Code lives in `src/`, runtime assets in
`res/`, current guides in `docs/`, and tests plus their fixtures/build inputs in
`tests/`. Python harness helpers add `src/` to their import path.

| Directory | Purpose |
| --- | --- |
| `harness/` | Reusable probes, controlled test runners, evidence logging and path resolution |
| `memory/` | Current source handoff |
| `notes/` | Dated decisions/reports describing only their recorded source and environment |
| `tmp/` | Ignored run logs, screenshots, scratch scripts and archived execution artifacts |
| `local-data/` | Ignored persistent runtime configuration, authorization receipts and virtual disks |

Use a distinct `tmp/` directory for every run. Never clean `local-data/` as scratch.
Historical notes and evidence are not current implementation instructions. Resolve
known relocated paths with `relocation.json`; deleted designs remain in Git history.
Do not replay instance-specific old scripts against an existing user deployment.

The [harness guide](harness/README.md) explains command capture and optional probes.
[Current handoff](memory/current.md) and [test instructions](../tests/README.md) give
maintained entry points. Entire `.agent/` content is excluded from product images.
