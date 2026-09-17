"""Acceptance harness regression tests; these are not product AT passes."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

import pytest

ROOT = Path(__file__).resolve().parents[2]
from harness import acceptance


@pytest.fixture
def harness_root(tmp_path, monkeypatch):
    """Exercise the CLI against an isolated source tree with no retired catalog."""
    original_fingerprint = acceptance.fingerprint
    original_safe_evidence = acceptance.safe_evidence
    monkeypatch.setattr(acceptance, "ROOT", tmp_path)
    monkeypatch.setattr(acceptance, "fingerprint", lambda: original_fingerprint(tmp_path))
    monkeypatch.setattr(acceptance, "safe_evidence", lambda path, root=None: original_safe_evidence(path, root or tmp_path))
    monkeypatch.setattr(acceptance, "environment", lambda: {"scope": "isolated regression test"})
    return tmp_path


def test_run_records_descriptive_test_ids_and_redacted_evidence_without_catalog(harness_root):
    result = acceptance.main([
        "run", "--id", "reader-check", "--kind", "automated", "--full-scenario",
        "--tests", "reader renders plain text", "--", sys.executable, "-c",
        "print('s' + 'k-' + 'abcdefghijk')",
    ])
    assert result == 0
    [record_path] = (harness_root / ".agent/tmp/evidence/runs").glob("*.json")
    record = json.loads(record_path.read_text())
    assert record["test_ids"] == ["reader renders plain text"]
    assert record["status"] == "passed"
    assert record["source_tree_sha256"] == acceptance.fingerprint()
    assert record["files"][0] == acceptance.safe_evidence(record["files"][0]["path"])
    output = (harness_root / record["files"][0]["path"]).read_text()
    assert "sk-abcdefghijk" not in output
    assert "[REDACTED_API_KEY]" in output


@pytest.mark.parametrize("command, source_changed", [
    ("raise SystemExit(3)", False),
    ("from pathlib import Path; Path('source.py').write_text('changed')", True),
])
def test_run_failure_or_source_change_cannot_record_a_pass(harness_root, command, source_changed):
    assert acceptance.main([
        "run", "--id", "source-bound-check", "--kind", "automated", "--",
        sys.executable, "-c", command,
    ]) == 1
    [path] = (harness_root / ".agent/tmp/evidence/runs").glob("*.json")
    record = json.loads(path.read_text())
    assert record["status"] == "failed"
    assert record["source_changed_during_execution"] is source_changed
    assert record["exit_code"] == (0 if source_changed else 3)


def test_blocked_records_descriptive_test_id_without_catalog(harness_root):
    assert acceptance.main([
        "blocked", "--id", "reader-check", "--tests", "reader renders plain text",
        "--reason", "Browser unavailable in isolated test",
    ]) == 0
    [path] = (harness_root / ".agent/tmp/evidence/runs").glob("*.json")
    record = json.loads(path.read_text())
    assert record["status"] == "blocked"
    assert record["test_ids"] == ["reader renders plain text"]
    assert record["reason"] == "Browser unavailable in isolated test"


def test_review_requires_current_source_and_independent_evidence(harness_root):
    review_path = harness_root / ".agent/tmp/review.json"
    evidence_path = harness_root / ".agent/tmp/inspection.log"
    review_path.parent.mkdir(parents=True)
    evidence_path.write_text("Reviewed the actual reader output.")
    record = {
        "id": "reader-review", "status": "passed", "test_ids": ["reader renders plain text"],
        "implementation_agent": "implementer", "reviewer_agent": "reviewer",
        "findings": "The reader output retains the original text.",
        "source_tree_sha256": acceptance.fingerprint(),
        "evidence_paths": [".agent/tmp/inspection.log"],
    }
    acceptance.write_json(review_path, record)
    (harness_root / "source.py").write_text("new behavior")
    with pytest.raises(ValueError, match="Review is stale"):
        acceptance.main(["review", str(review_path)])
    assert not (harness_root / ".agent/tmp/evidence/runs").exists()

    record["source_tree_sha256"] = acceptance.fingerprint()
    acceptance.write_json(review_path, record)
    assert acceptance.main(["review", str(review_path)]) == 0
    [path] = (harness_root / ".agent/tmp/evidence/runs").glob("*.json")
    saved = json.loads(path.read_text())
    assert saved["kind"] == "agent_review"
    assert saved["full_scenario"] is True
    assert saved["files"] == [acceptance.safe_evidence(".agent/tmp/inspection.log")]


@pytest.mark.parametrize("test_ids", ["reader-check", [""], ["   "], [None], [1]])
def test_record_rejects_malformed_descriptive_test_ids(test_ids):
    with pytest.raises(ValueError, match="descriptive strings"):
        acceptance.validate_record({
            "kind": "automated", "status": "blocked", "test_ids": test_ids,
            "source_tree_sha256": "a" * 64,
        })


@pytest.mark.parametrize("changes, message", [
    ({"source_tree_sha256": "unknown"}, "fingerprint"),
    ({"kind": "specification"}, "Specification checks"),
    ({"files": []}, "tangible evidence"),
    ({"exit_code": 1}, "exit code zero"),
])
def test_full_scenario_requires_source_and_successful_execution(harness_root, changes, message):
    (harness_root / "actual.log").write_text("Observed the actual behavior.")
    record = {
        "kind": "automated", "status": "passed", "test_ids": ["reader-check"],
        "source_tree_sha256": "a" * 64, "full_scenario": True, "exit_code": 0,
        "files": [acceptance.safe_evidence("actual.log")], **changes,
    }
    with pytest.raises(ValueError, match=message):
        acceptance.validate_record(record, harness_root)


class EvidenceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.source_tree = "a" * 64

    def record(self, kind="browser", status="passed", **changes):
        return {"id": kind, "kind": kind, "status": status, "source_tree_sha256": self.source_tree, "test_ids": ["reader renders plain text"], "full_scenario": True, **changes}

    def test_tampered_and_escaping_files_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "actual.log"
            path.write_text("first")
            file = acceptance.safe_evidence("actual.log", root)
            path.write_text("tampered")
            with self.assertRaises(ValueError):
                acceptance.validate_record(self.record(files=[file]), root)
            with self.assertRaises(ValueError):
                acceptance.safe_evidence("../missing.log", root)

    def test_self_review_rejected(self):
        with self.assertRaisesRegex(ValueError, "independent"):
            acceptance.validate_record(self.record("agent_review", reviewer_agent="a", implementation_agent="a"))

    def test_redaction_masks_keys_bearer_and_connection_credentials(self):
        raw = "sk-abcdefghijk Bearer abcdef\npassword=unsafe\npostgresql://role:secretword@db/library\npostgresql+psycopg://role:driversecret@db/library"
        result = acceptance.redact(raw)
        for secret in ["sk-abcdefghijk", "Bearer abcdef", "unsafe", "secretword", "driversecret"]:
            self.assertNotIn(secret, result)

    def test_file_memory_does_not_hide_production_source_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'.agent/notes').mkdir(parents=True);(root/'packages').mkdir()
            (root/'packages/app.py').write_text('first')
            before=acceptance.fingerprint(root)
            (root/'.agent/notes/work.md').write_text('agent progress only')
            self.assertEqual(before,acceptance.fingerprint(root))
            for directory in ('secrets','.local-data'):
                (root/directory).mkdir();(root/directory/'runtime.txt').write_text('sensitive runtime data')
            (root/'.env').write_text('BACKEND_KEY=test-only-sensitive-value')
            self.assertEqual(before,acceptance.fingerprint(root))
            (root/'packages/app.py').write_text('changed production behavior')
            self.assertNotEqual(before,acceptance.fingerprint(root))

    def test_url_credentials_and_sensitive_query_values_are_masked(self):
        raw='https://user:HTTP_PASSWORD@example.invalid/path?token=QUERY_TOKEN&safe=value&api_key=QUERY_KEY'
        result=acceptance.redact(raw)
        for secret in ('HTTP_PASSWORD','QUERY_TOKEN','QUERY_KEY'):
            self.assertNotIn(secret,result)
        self.assertIn('&safe=value',result)

    def test_exact_web_work_log_exclusion_keeps_neighboring_sources_bound(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            web = root / 'apps/web'
            (web / 'src').mkdir(parents=True)
            source = web / 'src/App.tsx'
            source.write_text('export const title = "first";')
            log = web / 'WORK_LOG.md'
            log.write_text('Independent browser work in progress.')
            before = acceptance.fingerprint(root)
            log.write_text('Independent browser work completed; evidence retained.')
            self.assertEqual(before, acceptance.fingerprint(root))
            source.write_text('export const title = "changed production behavior";')
            changed = acceptance.fingerprint(root)
            self.assertNotEqual(before, changed)
            (web / 'README.md').write_text('Changed documented application contract.')
            self.assertNotEqual(changed, acceptance.fingerprint(root))


if __name__ == "__main__":
    unittest.main()
