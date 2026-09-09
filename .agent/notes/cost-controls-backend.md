# Optional cost controls backend handoff — 2026-09-07

Owner `/root/ir_publisher_parser`: `packages/billing/*`, `packages/providers/settings.py`, `packages/domain/config.py`; parent owns schema/API/workflow/execution. No runtime configuration, real key or real Provider was accessed. No global memory changed.

## Public contract

- Frozen public profile: optional strict boolean `cost_control_enabled`. Raw legacy snapshots missing it remain monetarily controlled (`cost_control_enabled(profile)` defaults true).
- New settings saves default false. Omitted flag on an existing revision inherits its explicit flag; an old complete revision without the field inherits true; an old incomplete draft without the field can adopt false on its next save. The effective flag is decided under the settings lock, after idempotency replay lookup, so a replay cannot inherit a later toggle.
- Application defaults in `DEFAULT_PROVIDER_LIMITS`: input 32768, output 8192, unit characters 2000. These are application request bounds, not declarations of vendor/model capacity.
- Settings public views expose actual/effective values and `token_limits_defaults`. This view-only metadata never enters profile hashes, credential bindings or immutable profile files. Internal getters do not rewrite legacy snapshots.
- New saved revisions materialize all three limits. Omitted values inherit currently saved limits, then use application defaults if absent. Reset means a normal CAS PUT replacing only the three values with `token_limits_defaults`; there is no new action or permission flow. Endpoint/protocol/key retention rules remain unchanged.
- Enabled monetary controls require complete valid prices. Disabled controls allow missing/partial prices without inventing zero rates. Explicit malformed values and invalid limits remain rejected.

## Ledger / parent integration

- `reserve_cost(profile)` returns `None` when off. Parent added schema 11 nullable `Job.budget_micro` and `Permit.reserved_micro`, and nullable budget API paths.
- `authorize(session, lease, reserved_micro, price)` accepts `(None, None)` off. Every newly created Permit freezes the control boolean inside `price_snapshot`; legacy Permits missing it remain controlled. All modes still check lifecycle/fence, dispatch disabled, external-processing consent, one Permit per Attempt and at most two active reservations.
- Off bypasses monetary budgets. Optional complete usable price/usage can still produce a recorded actual cost; otherwise actual amount is `None`. A known HTTP result with unusable/missing usage can settle its Attempt without pretending its amount is zero. The raw received usage (or `None`) is retained, and repeated identical settlement is idempotent.
- Network uncertainty remains `mark_unknown`; no automatic resend or Permit release. Parent preserves response-model mismatch as an unknown result before settlement, independently of the monetary toggle.
- `budget_totals(session, job_id=None)` retains the three keys. A category containing an undetermined amount returns `None`; an empty category returns zero. `controlled_only=True` is the monetary-admission view: later controlled requests do not retroactively price or budget earlier uncontrolled requests. Current settings do not reinterpret existing Permit snapshots.
- Parent must tolerate nullable totals in API/UI and monetary summaries; it has updated workflow/execution/maintenance accordingly.

## Tests and evidence

- New `tests/unit/test_optional_cost_controls.py`: default off, default/public values, on requires rates, strict bool, no silent disable, idempotent replay after toggle, CAS reset/key binding, legacy external and managed hashes, omitted-limit inheritance, old incomplete adoption, partial rates.
- New `tests/integration/test_optional_cost_ledger.py`: real PostgreSQL no-price/missing-usage settlement, no fabricated free amount, optional known cost, unknown network / late settlement idempotency, concurrent cap, mixed historical/current monetary modes.
- Initial new unit evidence: `evidence/gemini-claude/optional-cost-first.xml` (9 failed, 8 passed before implementation). Compatibility first run: `optional-cost-ledger-compatibility-first.xml` (41 passed, old mandatory-price expectation failed under new default).
- Current owned suite: `optional-cost-owned-current.xml`: **71 passed**, 9.21 seconds, two existing Starlette/AnyIO deprecation warnings. Includes new tests, old budget concurrency/unknown tests, store and settings API tests. Test DB uses a distinct schema per test.
- Final view-consistency follow-up: initial `optional-cost-view-first.xml` exposed a stale missing-fields list on unconfigured views. `missing_fields` now uses the displayed effective limits/flag, while dispatch readiness still requires the persisted profile to be configured. No raw hash changed. Final suite `optional-cost-owned-final.xml`: **71 passed**, 9.87 seconds; these owned production files are ready for independent review.
- The global legacy `tests/integration/test_translation_execution.PROFILE` is unchanged. Historical store helper `complete()` now explicitly requests cost control; the old partial-config checks now assert missing price and defaulted limits, as required by the new behavior.
- `/root/acceptance_harness` has independently authored API probes and is reviewing the implementation. No independent pass is claimed until its actual report arrives.

## Remaining integration

Parent: four paid entrypoints, conditional budget UI/API, missing-usage/mismatched-model execution and migration regression. Web: current limits/default reset and costs-on toggle plus null amounts. No production instances were modified by this subtask.

## Final independent integration review and documentation freeze

- All owned production, tests and six documentation files are frozen. Later writes are evidence/notes only.
- Acceptance agent completed independent 8 settings/API plus 7 actual worker/ledger probes, all passed with no backend finding; see `evidence/cost-controls/independent-implementation-review.md`. Its separately rerun 16 UI contracts are mocked-API scope; actual deployed review remains assigned separately. This supersedes the earlier pending-review note, without altering old test evidence.
- I independently reran root's 17 optional workflow cases and added four excluded real-PostgreSQL boundary probes. All 21 independent nodes passed; the first XML includes one extra owned settings display case not counted as independent. Reports: `evidence/cost-controls/independent-root-workflow-review.{json,md}` and `independent-workflow-boundaries-final.xml`. No root production change was requested or made.
- The four probes establish persisted target + null amount when usage is missing, stale queued profile rejection before Provider construction, explicit unknown-risk acknowledgment without maintenance auto-resume, and actual schema10→11 old money/state preservation plus new nullable persistence. Synthetic Provider only.

### Documentation changed

- `README.md`: optional switch/default-off use, current/default token values and limits-only reset, known-valid versus unknown-network result distinction.
- `00-product-baseline.md`: new/legacy/incomplete config compatibility, nullable monetary fields, view-only defaults/hash contract and unchanged real-Provider authorization boundary.
- `shared/api-contract.md`: strict optional flag, all four nullable-budget entrypoints, frozen flags/amounts, read-only defaults metadata, normal CAS reset, unknown retry behavior; earlier native billing language now explicitly scoped to monetary controls enabled.
- `deployment/compose-contract.md`: same services/dependencies, immutable settings, schema11 two nullable columns, old value preservation and unchanged restore/dispatch gates.
- `milestones/M1-spec.md`: dated requirement supplement limits old mandatory-budget language to enabled scenarios; default/reset behavior and explicit real-Provider acceptance scope. Existing AT statements/IDs remain intact.
- `milestones/M1-plan.md`: dated implementation/validation supplement for optional costs, schema11, four entrypoints and default/reset checks.
- Snapshot hashes: `evidence/cost-controls/optional-contract-documentation-files.json`. No harness aggregate, catalog or historical acceptance evidence was rewritten.
