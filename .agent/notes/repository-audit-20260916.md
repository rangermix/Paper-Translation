# Repository audit · 2026-09-16

The user requested a repository-wide check for outdated, misplaced, redundant or
incorrect files after the prototype cleanup (`fdf8a61`). The starting inventory
contains 627 tracked files. The inventory records paths, sizes and hashes;
321 Python files parsed as AST and 51 JSON files parsed successfully. This is a
coverage record, not a claim that every execution path is proven correct.

## Findings and corrections

- Keep root `compose.yaml` and machine-specific `.vscode/settings.json` local.
  Both original files were preserved byte-for-byte. The user explicitly approved
  local-only Compose; shared definitions remain in `compose.example.yaml` and
  `deployment/`. The package verifier now has its own isolated Compose project.
- Replace duplicate `tools/validate_ir.py` with the production IR validator and
  check every schema. Remove unused prototype CSS from the management app;
  frozen reader resources and seed paper bytes remain unchanged.
- Fix Docling's recovery progress call, preserve malformed example URLs as text,
  and reject corrupt spool field types before they can crash the parser loop.
- Complete failed/partially completed semantic-review jobs honestly; retain known
  usage even when provider tracking IDs are malformed; use consistent lifecycle
  lock order when connection tests fail alongside settings changes. Include the
  actual normalization-version field in source diffs.
- Apply saved locale/publication defaults throughout workflow forms without
  overwriting draft choices; reset search pagination after filter changes; make
  the keyboard skip link focus current content without changing the hash route.
- Repair the offline harness mount, database-image environment name and portable
  interpreter-test path. Provide a repeatable memory-bounded Linux/PostgreSQL
  test image. Preserve the real parser resource guard instead of bypassing it.
- Make missing archived-review prerequisites explicit. Browser discovery no
  longer reads missing historical artifacts at import; live browser tests require
  both a designated URL and explicit opt-in and do not choose production port 8080.
- Exclude local/private configuration from acceptance source fingerprints without
  opening its bytes. Update the default Compose verifier's old 4 GiB / 128 PID bounds
  to the current 16 GiB / 256 PID / 4 CPU contract.
- Require explicit immutable image IDs for release inventory and report observed
  native dependencies instead of hardcoded historical library claims. Preserve
  previous evidence; each run writes a new output. Four old instance-mutating
  probes are archived byte-for-byte as non-executable historical source.
- Consolidate maintained product/deployment guidance: nonblocking content quality,
  all languages, optional monetary controls, enabled OCR assets, current parser
  defaults and on-demand local translation. Historical milestone IDs and evidence
  retain their provenance. Replace broken run-only document links with durable
  scope notes; archive stale handoff/status prose rather than treating it as current.

## Verification scope

Verification is performed against a dedicated `paper-audit-20260916-test` database
project and local frontend preview. No production deployment, real key access,
paid Provider call, model download or hardware inference is part of this audit.
Pinned dependency versions and immutable migrations/templates are not upgraded
merely because a newer release may exist. This is not a current vulnerability,
CUDA, Windows, full-model or release certification.

Verified code checkpoints were committed and pushed on `main`:

- `7c3c70c`: saved workflow preferences, navigation and frontend cleanup;
- `6fee132`: parser recovery, provider accounting, locking and source diffs.

The subsequent cleanup commit contains this report, local configuration rules,
maintained contracts, archived probes and the reproducible verification setup.
Resolve its exact ID from this file's Git history.

Verification results:

| Check | Result | Evidence in the root run directory |
|---|---|---|
| Full Linux/PostgreSQL suite | 1,214 passed, 18 historical-evidence skips | `pytest-linux-verified.log` |
| Final inventory/native-harness test revisions | 11 passed | `harness-image-verified.log` |
| Browser suite | 133 passed, 27 live/historical opt-in skips | `browser-full.log` |
| Frontend unit tests and production build | 18 passed; build succeeded | frontend domain logs |
| Portable repository contract checks | 51 passed | `package-verified.log` |
| Production, standalone CPU, CUDA, MLX, local translation, offline acceptance, test and verifier Compose configuration | All eight configurations passed static resolution | `compose-matrix.json` |
| Default Compose resource verifier | Passed after reproducing the obsolete-limit failure | `compose-harness-green.json` |
| Private-configuration fingerprint regression and related harness tests | 39 passed after reproducing four failures | `fingerprint-green.log` |

The full Linux run preceded final edits to two harness test files; those revisions
were checked with the separate 11-test run. Final review also tightened one
historical-evidence skip: an absent corpus can skip, but an existing incomplete or
corrupt corpus must fail. Its final boundary check and replay result are recorded
in `final-test-delta.log`; source/image binding is recorded in
`test-image-source-binding-verified.json`. These targeted checks are not added to
the full-suite count.

Final static coverage includes 640 existing tracked/new files: all 318 Python,
50 JSON and 3 TOML files parsed without errors. All 406 checked public source/data
files match the final test image. The four archived probes preserve their original
bytes; both local configuration files also remain byte-for-byte unchanged. Frozen
reader resources, templates and migrations have no changes. See
`static-verified.json` for the recorded checks.

The first full Linux run exposed four verification-environment failures (missing
parent evidence directories and absent built frontend assets); both causes were
fixed before the passing rerun. Original failure logs are retained. Two dependency
deprecation warnings remain in the passing run; no dependency versions were changed.

## Evidence and coverage

Root run: `.agent/tmp/repo-audit-20260916-01/` (inventory, static checks, regression
logs, Compose checks and final suite output). Independent domain reviews:

- `.agent/tmp/repo-audit-20260916-backend/coverage.json` and `findings.md`;
- `.agent/tmp/repo-audit-20260916-deployment/coverage.json` and test logs;
- `.agent/tmp/repo-audit-20260916-frontend/review-report.json` and browser logs.

Historical review-dependent tests may skip without their original archive. Their
skip reasons are part of the report; these checks cannot be certified by replacing
missing evidence with synthetic human review. Default browser checks use mocked
API responses, while explicitly enabled live/evidence checks remain separate.
