# Implementation and acceptance harness

Project-local working memories under `.agent/memory/` and root `.agent/notes/` are
excluded from source fingerprints. Root `secrets/`, `.agent/local-data/`, `.env` and
private `.env.*` files are never fingerprinted; `.env.example` remains source.
Production files, tests, contracts, fixtures
and harness implementation remain included. Reports and evidence are separately
hashed by each evidence record. This permits agent progress notes without
invalidating otherwise identical source, while changes to executable behavior
still invalidate previous full-scenario proof.

The contracts are the acceptance specification, not evidence that the product works.
This harness keeps the 130 scenarios and 24 exit gates tied to actual executions.
Run commands from the project root. The Python CLI uses only the standard library;
the supported product deployment remains Docker Compose.

```powershell
python .agent/harness/acceptance.py inventory
python .agent/harness/acceptance.py probe
python .agent/harness/acceptance.py run --id unit-regression --kind automated -- python -m pytest -q
python .agent/harness/acceptance.py report
python .agent/harness/acceptance.py gates
```

`run` captures the exact argument list, UTC time, duration, exit code, environment,
git commit, dirty state, source-tree digest and redacted command output. Execution
records and logs are append-only under `.agent/tmp/evidence/runs/`. A successful command is
not automatically a passed AT. Use `--tests M0-AT01A M0-AT01B` to attach supporting
evidence; `--full-scenario` additionally asserts that the command exercises every
Given/When/Then assertion of each listed scenario. Review the literal scenario
before making that assertion. Do not mark a static grep or schema check as a
complete product scenario.

Allowed evidence kinds are `specification`, `automated`, `compose`, `browser`,
`live_provider`, and `agent_review`. `specification` can never pass an AT.
FakeProvider executions are `automated`; they never count as `live_provider`.
Docker YAML/config checks are specification evidence, never a Compose cold start.

For a blocked scenario, save an explicit record with the concrete missing
prerequisite. Do not assume that Docker is absent from an old design note:

```powershell
python .agent/harness/acceptance.py blocked --id live-credentials --tests M1-AT08A M1-AT26A --reason "No approved model/profile, secret and capped external-processing test authorization"
```

An independent agent performs every scenario labelled `mixed` in the contracts.
Read `.agent/harness/AGENT_REVIEW.md`, copy the JSON template, perform the actual review,
and import it with `python .agent/harness/acceptance.py review path/to/review.json`.
Reviewer identities describe harness agents, never product accounts or end-user
`human_reviewed` values. Acceptance review does not create product ReviewRecords.

`report` writes `.agent/tmp/evidence/acceptance-report.json` and `.agent/IMPLEMENTATION_STATUS.md`.
Only current source-tree evidence counts. Mixed scenarios require both full
automated/browser/Compose/provider execution and independent agent review. Gates
also require the proof kinds in `.agent/harness/gate-policy.json`; M2 cumulative delivery
requires M0 and M1. `gates` exits nonzero for failed, blocked or not-run gates.
There is no waiver that converts missing evidence into a pass.

`.agent/harness/gate-prerequisites.json` makes explicit any literal gate evidence absent
from its requirement-ID list. M0-G06 names Docker-only cold start and recovery,
but the original contract lists only publication requirement M0-R14. Its gate
therefore additionally requires M0-AT18A/B; a publication crash test cannot stand
in for a clean-host deployment test. The original contracts remain unchanged.

Run `python .agent/harness/build_acceptance_observation_map.py` to join the four agents'
scoped observations and generate `.agent/tmp/evidence/observed-scenario-map.json` plus
`.agent/tmp/evidence/formal-gate-gap-report.md`. These keep actual behavior and precise gaps
visible while the source is changing. A historical literal-coverage assertion
never becomes a current gate pass merely by appearing in that map.

Keep file-based memory in `.agent/memory/`: state, decisions, ownership, commands,
findings and next actions. Never store secrets or claim unsupported completion.
