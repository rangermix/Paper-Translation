# Controlled live Provider execution

No real external request has been authorized or performed by this runner. Ordinary
pytest, the default command, and approval validation never create a Provider or
read the backend key. Actual execution is a separate explicit operation:

```powershell
python .agent/harness/live_provider_run.py
python .agent/harness/live_provider_run.py --approval C:/private/approved-test.json
python .agent/harness/live_provider_run.py --approval C:/private/approved-test.json --execute
```

The last command may incur paid usage and must only be run after the user has
approved the fixed model/profile, total budget and the exact controlled source
scope. Do not infer approval from this document or an example. Approval fields:

```json
{
  "approved": false,
  "approval_id": "unique-one-use-test-id",
  "scope": "controlled_eight_blocks_translation_candidate_semantic_review",
  "manifest_sha256": "SHA256 of fixtures/live-provider/manifest.json",
  "profile_file": "C:/private/public-provider-profile.json",
  "profile_sha256": "SHA256 of the fixed public profile",
  "secret_file": "C:/private/backend-key-file",
  "total_budget_micro": 1000000
}
```

The example budget is USD1; it grants no authorization. The public profile must
contain complete fixed prices/token bounds, semantic_review_enabled=true, and
exactly en→zh-Hans and zh-Hans→en. There is no model or price default. The key is
mounted only into the worker. Do not place key contents in the approval file.

Execution creates a separate Compose project on loopback18088, sets one shared
instance budget, uploads the two controlled PDFs, runs the actual offline parser,
compares all eight resulting text blocks to the approved manifest, and only then
confirms translation. It exercises a one-block candidate under a new controlled
glossary and a separate issue-only semantic review for each direction. It does
not accept candidates, create human ReviewRecords or publish unreviewed text.

Every approval ID is claimed once under `.agent/local-data/live-provider/`. Any partial,
failed or uncertain run retains the receipt, database/volume state and attempt
evidence; it cannot be automatically repeated with the same authorization. An
unknown result is not proof of an unsent request. The runner stops containers at
exit and retains all volumes. Inspect accounting before a new authorized run.

Successful transport still requires independent agent comparison of original
source, every translated block, candidate and semantic findings. Continue the
editor/QA/seal/publish/export/restore checks only after that review. No live result
can replace the separate research-PDF source gold or certify untested language
pairs. Evidence goes to `.agent/tmp/evidence/live-provider-runs/` and must be registered on
the actual stable source/image versions before an exit gate can pass.
