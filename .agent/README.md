# Agent workspace

Run maintained commands from the repository root. The application, tests,
fixtures and deployment sources live directly at that root.

| Directory | Contents | Git |
| --- | --- | --- |
| `harness/` | Reusable acceptance tools, policies and path resolvers | Tracked |
| `memory/` | Current handoff and durable agent context | Tracked |
| `notes/` | Working decisions and independent review summaries | Tracked |
| `tmp/` | Run logs, screenshots, reports, scratch scripts and archived evidence | Ignored |
| `local-data/` | Persistent local runtime configuration, authorization receipts and VM disks | Ignored |

Use a separate directory under `tmp/` for every new run. Historical evidence is
retained byte for byte; moving it does not certify the changed source tree.
Use `relocation.json` or the maintained harness resolvers to locate old relative
paths. Archived one-off scripts retain their original paths and are not current
entry points. Do not run them against an existing user instance.

Persistent local data is not disposable temporary output. Existing credential
files and used authorization receipts must survive reorganization. No agent
directory is copied into Docker images.

```powershell
python .agent/harness/acceptance.py --help
python -m pytest tests/acceptance/test_agent_path_migration.py -q
```

The original full M0/M1/M2 live-provider acceptance remains separately gated;
repository reorganization does not supply missing authorization or evidence.
