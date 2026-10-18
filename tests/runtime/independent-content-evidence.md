# Independent content browser inputs

Run [independent_content_evidence.py](independent_content_evidence.py) from the
repository root in the locked test environment, with `PYTHONPATH=src`. Use a new,
isolated output directory for every run. The generator refuses to overwrite one.
It does not need a database, model, HTTP server, frontend build or network access.

```sh
python tests/runtime/independent_content_evidence.py /evidence/generated \
  --source-revision <inspected-checkout-commit> \
  --image-id <inspected-locked-test-image-sha256> \
  --math-input /review-input
```

Mount current `src/`, `tests/`, `res/` and the reviewed input read-only. Give the
container a separate writable `/evidence` mount and disable its network. Do not
mount production volumes or credentials. The manifest records source, template,
fixture, review-plan, original-asset and output hashes.

Without `--math-input`, the tracked authored complex and hostile-text fixtures
are sufficient. Mathematics checks additionally require a reviewed source input
directory containing:

- `response.json`: the historical source, PDF inspection and original page-image
  storage keys.
- `remaining-math-reviewed-plans.json`: the hash-bound plan with 86 explicitly
  reviewed crop candidates, including the two `b63` caption expressions.
- `data/`: every source asset and original page PNG referenced by that response.

The generator treats those records as historical review decisions. It replays
them through the current correction/crop functions, compares every new crop to
the original page pixels, and renders fresh exports. This verifies current local
rendering/export behavior, not a fresh human review, parser/model run or API
transaction. Missing reviewed inputs must be reported; synthetic expressions
must not be substituted for the 86 reviewed references.

Wait for successful generation and `manifest.json` before running Playwright.
Set these environment variables to repository-relative paths under the generated
directory, then use `tests/browser/playwright.config.ts`:

| Variable | Generated subdirectory | Browser spec |
| --- | --- | --- |
| `LIBRARY_CAPTION_EVIDENCE` | `caption` | `caption-math-independent.spec.ts` |
| `LIBRARY_COMPLETE_MATH_EVIDENCE` | `all` | `complete-math-independent.spec.ts` |
| `LIBRARY_ANCHOR_EVIDENCE` | `anchor` | `reader-anchor-visibility.spec.ts` |
| `LIBRARY_COMPLEX_EVIDENCE` | `complex` | `complex-independent.spec.ts` |
| `LIBRARY_ENLARGEMENT_EVIDENCE` | `complex` | `reader-enlargement.spec.ts` |
| `LIBRARY_HOSTILE_EVIDENCE` | `hostile` | `hostile-independent.spec.ts` |

All six suites open fresh files via `file://`. Set `LIBRARY_BROWSER_OUTPUT` to a
separate temporary run directory. Frozen `reader-v1` and `reader-v2` resources
remain unchanged; exports are verified against their registered template hashes.
