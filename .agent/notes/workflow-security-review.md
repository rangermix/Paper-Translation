# Workflow review and dependency remediation

2026-09-06, agent `/root/ir_publisher_parser`. Project memory only.

## Reproduced defects and fixes

- Source import confirmation previously accepted superseded, previously sealed or outdated document-generation drafts. `workflow.seal_source` now enforces all three controls, records the sealed revision ID and preserves parser evidence.
- Existing source/new edition had no executable translation path. `GET /editions/{id}/preflight` and `POST /editions/{id}/translate` reuse the current sealed SourceRevision, verify Edition ETag/source hash/profile/budget/external confirmation and enqueue an independent draft. Existing draft presence rejects replacement and sends the user to editing/candidates. Undetermined and uncertified languages stay blocked.
- Profile snapshots gained derived glossary entries, but production execution compared them as deployment config and rejected every confirmed request as stale. The deployment comparison now excludes only the two known derived glossary fields. A test exercises the normal profile/secret selection path with an explicitly substituted Fake factory; it never sends the test key anywhere.
- A late semantic review could leave an earlier valid QA sealable. Current semantic result completion now invalidates draft QA; glossary changes mark findings stale. Root separately bound semantic evidence into QA fingerprints and seal checks.
- Root corrected same-target-language blocks to retained source with `same_language`, and fixed cached translation provenance. The focused mixed-source test first reproduced permanent unresolved output and now passes without creating a target segment or sending that block.
- Job and preflight responses now include stable frontend aliases for money, progress, attempt states, page coverage, asset entries and conservative cost estimates. Accounting fields retain their original nested forms as well.

## Evidence

`reports/core-evidence/workflow-review-tests.xml`: 17 real PostgreSQL/API + Fake-worker tests passed, including cancellation during a paid response (settlement recorded, zero new draft targets, no cancelled resume), new-source reuse, idempotency and stale ETag, source draft tombstones, unavailable languages, semantic QA invalidation, mixed-language retention and earlier translation concurrency/checkpoints.

`reports/core-evidence/security-upgrade-host-tests.xml`: 71 unit/integration tests passed after upgrading FastAPI, Starlette, Pillow and pypdf. Deprecation warnings concern Starlette's existing httpx-based test client; Provider remains the separately pinned httpx client.

## Dependency remediation in progress

The independent Trivy report found fixable high/critical Python issues in Docling, Pillow, lxml, pypdf, Starlette and Transformers. Updated exact pins: Docling 2.94.0, Pillow 12.3.0, lxml 6.1.0, pypdf 6.14.2, FastAPI 0.141.1, Starlette 1.3.1, Transformers 5.10.1. Official PyPI marked Transformers 5.10.0 yanked for missing fixes; 5.10.1 is the first non-yanked patch after the scanner's fixed-version floor. CPU Torch 2.8.0 and torchvision 0.23.0 remain explicitly pinned and had no high/critical entries in that report.

Docling 2.94.0 still supports the old layout spec, but its official model namespace moved from ds4sd to docling-project. The model lock retains the exact same commit IDs and file hashes while matching the new local namespace. Parser request/adapter/worker descriptors now derive version from the shared lock. Startup and each 60-second interval verify local model hashes before healthy heartbeats; model corruption removes the heartbeat and terminates any active child. No runtime model download was introduced.

Official sources read: https://github.com/docling-project/docling/releases/tag/v2.94.0 ; https://pypi.org/pypi/docling/2.94.0/json ; https://pypi.org/pypi/docling-slim/2.94.0/json ; https://raw.githubusercontent.com/docling-project/docling/v2.94.0/docling/datamodel/layout_model_specs.py ; https://raw.githubusercontent.com/docling-project/docling/v2.94.0/docling/models/stages/table_structure/table_structure_model.py . Real upgraded container inference and a new image vulnerability scan are required before closing remediation.


## Latest 2026-09-06 correction and verification

The earlier dependency paragraph is historical. Current exact remediation pins are pypdf 6.16.1, pypdfium2 5.13.0 (bundled PDFium 153.0.7999.0), torch 2.13.0+cpu and its officially matched torchvision 0.28.0+cpu, with opencv-python-headless 5.0.0.93 replacing the unused GUI distribution through uv exclude-dependencies. Deployed uv was upgraded to fixed 0.10.7 because 0.8.15 did not understand this setting. Acceptance owns pinned OCI digests and the runtime's removal of Qt/OpenGL/glib and pip. New candidate image builds and scans are independent acceptance work; no zero-vulnerability claim is made.

The first true upgraded Docling inference on Efficient produced 18 pages / 254 blocks / 44 unresolved items. Independent agent inspected all 18 original pages and 22 crops, recorded failures in evidence/security-upgrade-efficient/INDEPENDENT_SOURCE_REVIEW.md. These are retained failure evidence.

Parser fidelity fixes now reconcile Docling geometry with the original PDF's form clipping boxes; retain model-misclassified figure text in the actual graph image; separate cross-page false merges using original charspans; bind caption references with Pydantic aliases; associate explicit same-page captions and shared panels; retain all display formulas as original raster crops; derive numbered heading levels and parents; recognize the explicit bibliography section; restore native punctuation only when letter/digit order is exactly preserved; and restore wrapped visible URLs only against their original PDF annotation with whitespace/hyphen differences. Reconciliation before/after evidence is stored in inspection.reconciliations. Renderer v1 CSS is untouched.

PDFium 153 changed page-object helper get_pos to get_bounds; the latter includes invisible content outside Form /BBox, so the adapter now intersects transformed original Form boxes. A real-original-PDF regression reproduces this issue. New failure-first fidelity tests include formula image retention, aliases/shared panels, cross-page plot title removal, native punctuation with discretionary line breaks, URL wrapping safeguards and heading ancestry.

reports/core-evidence/core-unit-current.xml: 63 unit tests passed after all current changes. Earlier replay-v2 of frozen real inference reduced 44 issues to one actual inline square-root/fraction in prose on page 6; it remains blocking. evidence/fidelity-replay-efficient-v2/INDEPENDENT_SPOT_REVIEW.md independently verifies selected repaired crops but explicitly does not claim a new inference or full source-gold pass. Fresh candidate inference and full paper agent review remain required.

No paid Provider test was run, and no external processing or spend authorization was inferred.
