# Historical probe source

These source snapshots are retained byte for byte for provenance. The `.py.txt`
extension marks them as archival text, not runnable current entry points. Do not
run them against an existing user instance. Historical notes may retain their
former `.agent/harness/` paths.

| Snapshot | Why it was retired |
| --- | --- |
| `verify_provider_settings_runtime.py.txt` | Targets the September 6 `bilingual-ai-settings-20260906` project on port 18086, overwrites provider settings and recreates containers, and reuses one evidence directory. Its incomplete-profile expectation predates optional cost controls and default token limits. |
| `verify_native_provider_runtime.py.txt` | Targets the September 6 `bilingual-native-20260906` project on port 18088 with the same mutations and reused output. Its `DISPATCH_DISABLED` environment check does not verify the database dispatch setting. |
| `backup_roundtrip.py.txt` | Defaults to the production Compose project and port 8080, consumes a previous smoke result, mutates metadata, and performs `restore --replace`. It overwrites fixed evidence files. |
| `legacy_roundtrip.py.txt` | Defaults to the production Compose project and port 8080, runs the seed command and creates exports, and overwrites fixed evidence files. |

The provider projects were handed over to the user; the September 6 and 7 notes
explicitly prohibit reusing these probes because user configuration may have
changed. See [the native-provider handoff](../gemini-claude-20260906.md) and
[the archived repository handoff](../handoff-before-repository-audit-20260916.md).

Current settings and native transport coverage lives in
`tests/integration/test_provider_settings_api.py`,
`tests/integration/test_native_provider_integration.py`,
`tests/integration/test_dispatch_settings.py`,
`tests/unit/test_provider_settings_store.py`, and
`tests/unit/test_native_provider_transport.py`. Those tests do not replace real
Compose or real-model acceptance.

For an isolated Compose backup/restore exercise, use
`.agent/harness/offline_compose_roundtrip.py` with prepared acceptance images and
available acceptance ports. It creates fresh projects with internal networks,
runs `offline_product.py` to read both seeded documents and create four worker
exports, and compares stored bytes after restoration into another fresh project.
Its run records are retained under `.agent/tmp/evidence/offline-compose/runs/`;
shared output and fixed ports mean it must not run concurrently with itself.
`tests/integration/test_legacy_seed.py` separately checks seed idempotency,
navigation-only HTML changes, frozen CSS and source-free exports. These are
distinct checks, not a claim that the current tree has rerun every historical
probe assertion.
