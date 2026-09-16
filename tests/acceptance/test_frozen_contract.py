"""Implementation prerequisites only, not live product acceptance."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class FrozenContractTests(unittest.TestCase):
    def test_all_reference_bytes_match_allowlist(self):
        manifest = json.loads((ROOT / "reference/reference-files.sha256.json").read_text(encoding="utf-8-sig"))
        self.assertGreater(len(manifest), 20)
        for relative, expected in manifest.items():
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected)

    def test_reader_mutation_would_fail_frozen_digest(self):
        data = (ROOT / "reference/reader-v1.css").read_bytes()
        expected = "51dacbcd96a21214ed83a62cad870a6281eb20db1aa260f3a7d782c58fdd18a8"
        self.assertEqual(hashlib.sha256(data).hexdigest(), expected)
        self.assertNotEqual(hashlib.sha256(data + b" ").hexdigest(), expected)

    def test_scope_has_pdf_only_and_no_removed_capability(self):
        scope = json.loads((ROOT / "contracts/scope.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(scope["document_source_kinds"], ["pdf_upload"])
        self.assertEqual(scope["supported_upload_mime_types"], ["application/pdf"])
        self.assertEqual(scope["deployment"], "docker_compose_only")
        for key in ["url_import_enabled", "automatic_remote_assets", "identity_system", "login_enabled", "teams_enabled", "acl_enabled", "reverse_proxy_included", "runtime_dependency_downloads"]:
            self.assertIs(scope[key], False, key)

    def test_legacy_pages_are_exactly_two_and_include_pdf_sources(self):
        manifest = json.loads((ROOT / "reference/reference-files.sha256.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(len([key for key in manifest if key.startswith("reference/legacy/") and key.endswith(".html")]), 2)
        self.assertEqual(len([key for key in manifest if key.startswith("reference/legacy/source/") and key.endswith(".pdf")]), 2)


if __name__ == "__main__":
    unittest.main()
