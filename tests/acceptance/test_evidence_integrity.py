"""Acceptance harness regression tests; these are not product AT passes."""
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
from harness import acceptance


class EvidenceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tests = {"M0-AT02A": {"requirement_id": "M0-R02", "mode": "mixed", "scenario": "Actual browser plus agent review"}}
        self.gates = [{"id": "M0-G01", "requirements": ["M0-R02"], "milestone": "M0", "title": "test", "evidence": "actual review"}]
        self.source_tree = "a" * 64
        self.policy = {"M0-G01": ["browser", "agent_review"]}

    def record(self, kind="browser", status="passed", **changes):
        return {"id": kind, "kind": kind, "status": status, "source_tree_sha256": self.source_tree, "test_ids": ["M0-AT02A"], "full_scenario": True, **changes}

    def result(self, records):
        return acceptance.aggregate(self.tests, self.gates, records, self.source_tree, self.policy)

    def test_empty_ledger_cannot_complete_gate(self):
        tests, gates = self.result([])
        self.assertEqual(tests["M0-AT02A"]["status"], "not_run")
        self.assertEqual(gates[0]["status"], "not_run")

    def test_successful_specification_and_supporting_tests_are_insufficient(self):
        records = [self.record("specification"), self.record("browser", full_scenario=False)]
        self.assertEqual(self.result(records)[1][0]["status"], "not_run")

    def test_mixed_scenario_needs_independent_review(self):
        self.assertEqual(self.result([self.record()])[0]["M0-AT02A"]["status"], "not_run")
        records = [self.record(), self.record("agent_review")]
        self.assertEqual(self.result(records)[1][0]["status"], "passed")

    def test_stale_success_is_not_current_evidence(self):
        records = [self.record(), self.record("agent_review", source_tree_sha256="b" * 64)]
        self.assertEqual(self.result(records)[1][0]["status"], "not_run")

    def test_latest_failure_requires_rerun_of_same_kind(self):
        records = [self.record(), self.record("agent_review"), self.record("browser", "failed")]
        self.assertEqual(self.result(records)[1][0]["status"], "failed")
        records.append(self.record())
        self.assertEqual(self.result(records)[1][0]["status"], "passed")

    def test_fake_provider_cannot_meet_live_provider_gate(self):
        self.policy["M0-G01"].append("live_provider")
        records = [self.record(), self.record("agent_review"), self.record("automated")]
        self.assertEqual(self.result(records)[1][0]["status"], "not_run")

    def test_gate_text_prerequisite_cannot_be_replaced_by_unrelated_compose_proof(self):
        self.tests['M0-AT18A'] = {'requirement_id': 'M0-R18', 'mode': 'mixed', 'scenario': 'Clean Docker-only host'}
        records = [self.record(), self.record('agent_review'), self.record('compose')]
        _, gates = acceptance.aggregate(self.tests, self.gates, records, self.source_tree,
            self.policy, {'M0-G01': ['M0-AT18A']})
        self.assertEqual(gates[0]['status'], 'not_run')
        self.assertIn('M0-AT18A', gates[0]['test_ids'])

    def test_tampered_and_escaping_files_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "actual.log"
            path.write_text("first")
            file = acceptance.safe_evidence("actual.log", root)
            path.write_text("tampered")
            with self.assertRaises(ValueError):
                acceptance.validate_record(self.record(files=[file]), self.tests, root)
            with self.assertRaises(ValueError):
                acceptance.safe_evidence("../missing.log", root)

    def test_self_review_rejected(self):
        with self.assertRaisesRegex(ValueError, "independent"):
            acceptance.validate_record(self.record("agent_review", reviewer_agent="a", implementation_agent="a"), self.tests)

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
