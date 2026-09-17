# Contract ownership and status

Runtime [JSON Schemas](../../res/schemas/) define serialized boundaries, including
legacy records that must remain readable. This directory contains planning and
acceptance tracking data, not runtime resources. `scope.json` and `workflow-states.json` describe current
scope and state compatibility. `res/schemas/nonblocking-contract.schema.json` and the NB
backlog describe the later content-quality workflow; the original-only and history
contracts are maintained under `docs/shared/`.

`requirements.json`, `implementation-backlog.json`, `exit-gates.json`,
`traceability.csv`, and `change-map.json` retain the original M0–M2 planning IDs
and mappings. Their `planned`, `not_started`, and `not_evaluated` fields are not
live implementation status. Later decisions in `docs/product-baseline.md` supersede
conflicting quality gates, experimental-language restrictions, mandatory monetary
budgets, and CPU-only assumptions. Do not rewrite old evidence to claim that a
new policy passed an earlier source-bound test.

`src/tools/check_package.py` checks all schema syntax and uses the production
`packages.ir` validator for fixture semantics. It also checks the planning graph,
portable Compose definitions and frozen seed resources. It does not run models or
certify an application release. Current execution evidence is described by
`.agent/memory/current.md` and the acceptance harness.
