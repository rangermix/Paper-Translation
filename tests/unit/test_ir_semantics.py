"""M0 IR exit regressions. Fixtures are copied in memory, never rewritten."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from packages.ir import IRValidationError, block_hash, canonical_bytes, digest, strict_loads, validate_ir

ROOT = Path(__file__).resolve().parents[2]


class IRSemantics(unittest.TestCase):
    def setUp(self):
        self.ir = json.loads((ROOT / 'tests/fixtures/sample-document.json').read_text('utf-8'))

    def rejected(self, mutation):
        mutation(self.ir)
        with self.assertRaises(IRValidationError):
            validate_ir(self.ir)

    def test_frozen_all_kinds_fixture(self):
        self.assertIs(validate_ir(self.ir, ROOT / 'tests'), self.ir)

    def test_duplicate_json_keys(self):
        with self.assertRaises(IRValidationError):
            strict_loads('{"x":1,"x":2}')

    def test_nan_rejected(self):
        with self.assertRaises((IRValidationError, ValueError)):
            canonical_bytes({'x': float('nan')})

    def test_canonical_unicode_no_compatibility_normalization(self):
        self.assertEqual(canonical_bytes({'z':'😀', 'a':'ﬁ'}), '{"a":"ﬁ","z":"😀"}'.encode())

    def test_duplicate_block(self):
        self.rejected(lambda v: v['source_revision']['blocks'].append(copy.deepcopy(v['source_revision']['blocks'][0])))

    def test_parent_cycle(self):
        self.rejected(lambda v: v['source_revision']['blocks'][0].update(parent_id='p1'))

    def test_owner_kind_mismatch(self):
        self.rejected(lambda v: v['source_revision']['blocks'][6].update(owner_id='p1'))

    def test_orphan_root_cell(self):
        def change(v):
            v['source_revision']['blocks'][9]['owner_id'] = None
            v['source_revision']['reading_order'].append('c1')
        self.rejected(change)

    def test_missing_target(self):
        self.rejected(lambda v: v['translation_revision']['results'].pop())

    def test_prose_cannot_bypass_translation(self):
        def change(v):
            v['source_revision']['blocks'][1]['translatable'] = False
            v['translation_revision']['results'][1].update(status='retained', target_inline=[], reason='original_figure')
        self.rejected(change)

    def test_protected_multiplicity(self):
        self.rejected(lambda v: v['translation_revision']['results'][1]['target_inline'].append({'type':'protected_ref','ref':'n64'}))

    def test_source_hash_drift(self):
        self.rejected(lambda v: v['source_revision']['blocks'][1].update(normalized_text='Altered'))

    def test_bounds_nonfinite(self):
        self.rejected(lambda v: v['source_revision']['blocks'][0]['provenance'][0]['bbox'].__setitem__(0,float('nan')))

    def test_unknown_fields(self):
        self.rejected(lambda v: v['document'].update(workspace_id='bad'))

    def test_table_overlap(self):
        def change(v):
            b = next(b for b in v['source_revision']['blocks'] if b['kind']=='table')
            b['attributes']['cells'][1]['column'] = 0
            b['source_hash'] = block_hash(b,v['source_revision']['protected_atoms'])
        self.rejected(change)

    def test_unresolved_release(self):
        self.rejected(lambda v: v['translation_revision']['results'][1].update(status='unresolved'))

    def test_path_traversal(self):
        self.rejected(lambda v: v['source_revision']['assets'][0].update(storage_key='a/../escape.pdf'))

    def test_missing_asset(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(IRValidationError):
            validate_ir(self.ir, Path(folder))

    def test_target_invents_link(self):
        self.rejected(lambda v: v['translation_revision']['results'][1]['target_inline'].append({'type':'link','href':'https://example.org','text':'bad'}))

    def test_fake_review(self):
        self.rejected(lambda v: v['translation_revision']['results'][1].update(review_state='human_reviewed'))


if __name__ == '__main__':
    unittest.main()
