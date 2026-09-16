# Contract ownership and status

The JSON Schemas define current serialized boundaries, including legacy records
that must remain readable. `scope.json` and `workflow-states.json` describe current
scope and state compatibility. `nonblocking-contract.schema.json` and the NB
backlog describe the later content-quality workflow; the original-only and history
contracts are maintained under `shared/`.

`requirements.json`, `implementation-backlog.json`, `exit-gates.json`,
`traceability.csv`, and `change-map.json` retain the original M0–M2 planning IDs
and mappings. Their `planned`, `not_started`, and `not_evaluated` fields are not
live implementation status. Later decisions in `00-product-baseline.md` supersede
conflicting quality gates, experimental-language restrictions, mandatory monetary
budgets, and CPU-only assumptions. Do not rewrite old evidence to claim that a
new policy passed an earlier source-bound test.

`tools/check_package.py` checks all schema syntax and uses the production
`packages.ir` validator for fixture semantics. It also checks the planning graph,
portable Compose definitions and frozen seed resources. It does not run models or
certify an application release. Current execution evidence is described by
`.agent/memory/current.md` and the acceptance harness.
