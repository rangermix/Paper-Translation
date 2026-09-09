# Python harness relocation

Current repository root is `C:/workspaces-local/Paper-Translation`. Executable Python harness code is `.agent/harness`; pytest imports it through `pythonpath = [".", ".agent"]`. Direct CLI example: `.venv/Scripts/python.exe -B .agent/harness/acceptance.py --help`.

`_project.py` locates the root by pyproject/packages markers, and uses `/app` for reviewed test helpers mounted at `/harness`. Safe legacy relative artifact paths are resolved without changing archived JSON or hashes. One former project prefix is accepted; arbitrary absolute/parent/link paths are rejected. The relocation contract is checked against `.agent/relocation.json`.

New evidence/reports and pytest/mypy caches live in `.agent/tmp`. `.agent/local-data` remains persistent authorization/VM state and is excluded from source fingerprint, along with temporary outputs and agent notes/memory. All `.local-data` directories are pruned before walking, including the locked legacy VM parent.

Final validation: 48 focused tests passed, 0 skipped; 165 Python sources compiled without bytecode writes; 6 safe CLI/help/fingerprint checks passed; prior full collection found 727 tests before 3 final mapper cases were added. No full-suite, Docker, Provider, evidence report regeneration or historical byte rewrite was performed. Exact evidence and current helper hashes: `.agent/tmp/evidence/path-migration/python-path-migration-review.json`.

Historical acceptance records remain historical. Prefix relocation can recover a moved immutable artifact, but it cannot make modified maintained source match an old SHA or certify the new tree.
