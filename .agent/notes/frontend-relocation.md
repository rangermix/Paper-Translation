# Frontend/browser relocation · 2026-09-07

The project now runs directly at `C:/workspaces-local/Paper-Translation`. This task changed maintained browser-test paths only; production frontend files, reader CSS, historical artifacts and their internal evidence bytes were not edited. `apps/web/node_modules`, `dist` and TypeScript build cache remain in their standard locations.

## Paths

- `tests/browser` retains its relative imports of `../../apps/web/node_modules/@playwright/test`.
- `.agent/harness/browser_paths.cjs` resolves the actual project root and maps only known old input prefixes (`evidence/`, `apps/web/evidence/`, `reports/`, including the former absolute project prefix). The old `latest-anchor-review.txt` bytes remain untouched; its value is mapped when read.
- Default browser reports, screenshots, traces and test outputs use a fresh `.agent/tmp/frontend/runs/<UTC-and-UUID>/` directory. `LIBRARY_BROWSER_OUTPUT` can select another directory inside `.agent/tmp`; outside paths are rejected. Existing explicit screenshot variables also use that output guard.
- Historical math, hostile-reader, draft, complex-reader and anchor inputs are read separately from `testInfo.outputPath` outputs. No rerun writes its screenshots or review JSON alongside those historical inputs.
- Live-library/resilience/storage checks share the current run's `live/` output directory. Running storage separately requires `LIBRARY_LIVE_RECEIPT` pointing to the intended prior receipt; it no longer silently reads an old run's fixed filename.
- Maintained CJS checks (`reader_browser`, `legacy_browser`, `complex_reader_browser`) use the shared root helper and a fresh output directory. Read-only input overrides are `READER_BROWSER_INPUT`, `LEGACY_BROWSER_INPUT`, `COMPLEX_READER_INPUT`; the old `COMPLEX_READER_OUTPUT` input-directory override remains a compatibility alias.
- Persistent local state belongs to `.agent/local-data`, not `.agent/tmp/local-data`. Historical `.agent/tmp/frontend/evidence` scripts were not rewritten or executed.

## Verification performed

All new execution evidence is in `.agent/tmp/repository-layout/frontend/`.

- `npm --prefix apps/web run test`: 13 passed.
- `npm --prefix apps/web run build`: passed; assets remain `index-6muiN2d7.js` and `index-BEgjW6yP.css`.
- Playwright `--list --reporter=line`: 96 tests in 15 files collected; zero browser tests executed.
- Four maintained CJS files passed `node --check`.
- Five old-input mappings, nine outside/traversal input rejections, five invalid output-path rejections, a valid output path, and the actual archived anchor pointer/reader target passed the direct path check.

Independent IR review found that the first input mapper could return paths outside the repository. The corrected helper accepts absolute inputs only under the exact current/former root, rejects traversal/UNC/drive-relative paths, and verifies the resolved repository boundary. The prior helper, report and check receipt are preserved with `before-input-guard` names. A second browser collection after this fix again collected 96 cases without executing any; unit/build inputs were unchanged.

`review.json` binds the edited-file hashes and exact command outputs. No live endpoint, provider, old browser profile or running Docker service was accessed. Full historical UI certificates were not regenerated or relabelled.

For another bounded collection check from the root:

```powershell
$env:LIBRARY_BROWSER_OUTPUT = Join-Path $PWD '.agent/tmp/repository-layout/frontend/collection'
node apps/web/node_modules/@playwright/test/cli.js test --config tests/browser/playwright.config.ts --list --reporter=line
```
