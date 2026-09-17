# Repository cleanup verification · 2026-09-17

Cleanup commit: `331a642`, following layout commit `38b82d8`. This is a dated
source/build record, not a production deployment or model-certification report.
The user's initial README/AGENTS edits and removal of `sources.md` are included.

## Result

- Removed project release branding, completed milestone/spec/plan trees, duplicate
  contract registries, obsolete release reports and the harness catalog that
  consumed them. Current guides describe implemented behavior and actual commands.
- Moved test Compose files and their Dockerfile into `tests/`; removed the redundant
  verifier Compose/image and separate requirements file. Repository checks reuse
  the locked test image with no runtime network or database dependency.
- Moved authored corpora into `tests/fixtures/`, updated direct and dynamic readers,
  and supplied explicit read-only fixture mounts to disposable harnesses. Production
  app images no longer contain test corpora. Runtime inputs remain in `res/`.
- Removed eight unused resource inputs: the duplicate artifact-manifest,
  import-request, translation-response and nonblocking JSON schemas; the import and
  provider-output examples; the unused cross-page original figure; and the security
  generator's intermediate raster. The raster is now generated in memory.
- Updated the two older PDF-security/cross-page probes to describe current
  nonblocking diagnostics while retaining their resource and content assertions.

Persisted schema/template IDs, frozen reference bytes, database migrations,
third-party versions and historical path aliases remain compatible. Frontend
package metadata now matches the backend's `0.1.0`; the dependency graph is unchanged.
All remaining deployment inputs and resource corpora have identified consumers.

## Executed verification

Main evidence directory:
[`repo-current-cleanup-20260917T072000Z`](../tmp/repo-current-cleanup-20260917T072000Z/).

| Check | Result | Evidence file in that directory |
| --- | --- | --- |
| Rebuilt Linux/PostgreSQL suite | 1,224 passed, 18 skipped, 2 dependency deprecation warnings | `full-pytest-final.log` |
| Frontend unit tests | 18 passed | `frontend-unit.log` |
| Browser suite | 133 passed, 27 skipped | `browser.log` |
| Repository checks, isolated container and host | 6 passed in each | `container-checks-final.log`, `host-checks-final.log` |
| Compose configurations | 9 resolved successfully; static validation only | `static-verification.json` |
| Python/JSON/TOML syntax | 319 / 32 / 2 files passed | `static-verification.json` |
| Frozen runtime bytes | 50 files unchanged from `38b82d8`; IR schema changed only filename/title | `static-verification.json` |
| Production app build | Linux amd64 build, including TypeScript/Vite, passed | `app-build.log` |
| Isolated app startup | Liveness, frontend, capabilities, 2 seeds, 3 templates, 13 migrations; no bundled tests | `app-smoke.log` |
| App source/resource binding | 155 files match the final checkout | `app-image-source-binding.json` |

Full backend command:

```sh
docker compose -p paper-cleanup-20260917 -f tests/compose.yaml --profile tests run --rm tests python -m pytest -q -rs --maxfail=1
```

Earlier runs exposed dynamic asset readers still using the former fixture root.
Those failures and the interrupted first full run remain in the evidence directory;
the final full run above followed the path fixes and rebuilt test image.

App image: `paper-cleanup-app:20260917`,
`sha256:f0201c0a7f30314b70498519fc1d2d039f3d1c21ec6ad0188c68f3c01c78d2e2`.
It was built from the worktree before committing; its label is not a final-commit
claim. The separate file comparison binds its runtime inputs to the committed tree.
Smoke execution used UID 10001, a read-only filesystem, no network and no production
volumes. It did not exercise the parser model, database workflow or real providers.

Final maintained-source fingerprint from `acceptance.py fingerprint`:
`6a37521e4929011fbe547bf5e2de8c6f80a8f6544bf81343e5b4871ba7fe5c3c`.
Agent notes/handoff files are excluded from that fingerprint.

## Review and scope limits

- [Documentation review](../tmp/repo-current-doc-recheck-20260917T074047Z/review.md):
  17 guides, 73 links; corrected deployment target and export-directory instructions.
- [Resource/dynamic-path review](../tmp/repo-current-cleanup-final-resource-review-20260917-backend/review.md):
  all 64 original inputs accounted for; fixture hashes, 40 aliases and security
  generation verified.
- [Harness mounts](../tmp/repo-current-cleanup-fixture-mounts-bi7e67o_/summary.md):
  six generated Compose configurations and 40 authorization/path tests passed.
- [Nonblocking probe repair](../tmp/repo-current-cleanup-nonblocking-harness-7m7ywy20/summary.md):
  25 targeted tests and 15 synthetic assertion cases passed. Full model-backed
  execution of these optional probes was not performed.

Skipped backend/browser checks require archived independent evidence or explicit
live-instance opt-in. No model download, real inference, provider call, credential
read or production redeployment was performed. The dedicated test project/database
and Vite server were stopped. Root local Compose is ignored and byte-identical to
the pre-cleanup file; persistent local data and archived evidence were preserved.
