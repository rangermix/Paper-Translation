# Independent agent verification

The user explicitly assigned all formerly manual verification to agents. The
coordinator must allocate a bounded review to an agent other than the implementer
of the reviewed behavior. A reviewer can test code or inspect produced documents;
it cannot infer a browser rendering, real model result or Docker cold start from
source alone. Use existing source PDFs to check extraction gold, not legacy English
HTML or the old translation. Preserve uncertainties as findings.

1. Read the literal scenario and related gate in `docs/contracts/`.
2. Read `.agent/memory/current.md` and the implementation's command/evidence.
3. Independently run the scenario or inspect the genuine artifact/output.
4. Record exactly what was observed. For visual checks cover layout, colors,
   hierarchy, tables/sidebar, controls and mobile wrapping at 1440x1060 and
   390x844; include 320px when required. For translation review compare source
   meaning, numbers, units, negation, limitations and terminology.
5. Include evidence paths and hashes, test IDs, reviewer and implementer agent
   IDs, source-tree digest, browser/environment, findings and remaining limits.
6. A missing credential, unavailable runtime or unexecuted action is `blocked`
   or `not_run`. Do not replace it with a generated screenshot or a fake response.
7. Import the record; the harness will refuse self-review, absent files, stale
   code, empty findings or a successful review without evidence.

Use `python .agent/harness/acceptance.py fingerprint` for `source_tree_sha256`. Paths are
relative to the project. Store a review JSON under `.agent/tmp/evidence/reviews/` first.

```json
{
  "id": "agent-review-descriptive-name",
  "reviewer_agent": "/root/independent_reviewer",
  "implementation_agent": "/root/implementer",
  "test_ids": ["M0-AT02A"],
  "status": "not_run",
  "source_tree_sha256": "replace-with-current-fingerprint",
  "environment": {"browser": "not_run", "viewport": "not_run"},
  "evidence_paths": [],
  "findings": ["Actual observations, failures and uncertainty go here."],
  "limitations": ["This template is not completed verification."]
}
```
