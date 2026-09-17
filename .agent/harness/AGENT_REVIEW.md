# Independent review evidence

Review the current request, implementation and genuine output independently of the
implementer. Record what was inspected or executed and what remains untested.
Source inspection cannot prove browser rendering, model output or a Docker cold start.
For extraction review compare the original PDF, not an existing translation.

`acceptance.py review` rejects self-review, absent evidence, changed file hashes,
stale source fingerprints and empty findings. Agent identities here describe
reviewers, never application users or product human-review records.

Get the source hash with `python .agent/harness/acceptance.py fingerprint`, save
this structure with actual observations under a unique `.agent/tmp/` directory,
and import it with `python .agent/harness/acceptance.py review PATH`:

```json
{
  "id": "descriptive-review",
  "reviewer_agent": "/root/reviewer",
  "implementation_agent": "/root/implementer",
  "test_ids": ["behavior-or-test-name"],
  "status": "not_run",
  "source_tree_sha256": "replace-with-current-fingerprint",
  "environment": {},
  "evidence_paths": [],
  "findings": ["Actual observations belong here."],
  "limitations": ["This template is not completed verification."]
}
```

Record missing runtime/credentials or unexecuted checks as blocked/not run. Do not
manufacture evidence or interpret a passing test double as real model validation.
