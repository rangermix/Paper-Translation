"""Independent target/source attribution using real API reads of authored snapshots."""
import copy

import pytest

from packages.ir import block_hash, validate_source
from tests.integration.test_revision_diff_axes import sample, changed_source, seed, compare

pytestmark = pytest.mark.postgres


def test_target_cross_reference_ids_can_drift_without_text_change(client, database):
    data = sample()
    before, tx = data['source_revision'], data['translation_revision']
    after, ty = changed_source(before), copy.deepcopy(tx)
    ids = {b['id']: 'renumbered-'+b['id'] for b in after['blocks']}

    def remap(value):
        if isinstance(value, list):
            return [remap(item) for item in value]
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if isinstance(item, str) and (key in {'id', 'parent_id', 'owner_id', 'block_id'} or key.endswith('_block_id')):
                    result[key] = ids.get(item, item)
                elif key == 'reading_order' or key.endswith('_block_ids'):
                    result[key] = [ids.get(bid, bid) for bid in item]
                else:
                    result[key] = remap(item)
            return result
        return value

    after, ty = remap(after), remap(ty)
    for block in after['blocks']:
        block['source_hash'] = block_hash(block, after['protected_atoms'])
    validate_source(after)
    seed(database, before, after, tx, ty)
    result = compare(client, tx['id'], ty['id'], 'target')
    assert result.status_code == 200, result.text
    assert not any(row['kind'] in {'added', 'deleted'} or 'content' in row['aspects'] for row in result.json()['changes'])


def test_same_target_atom_id_with_changed_value_is_content(client, database):
    data = sample()
    before, tx = data['source_revision'], data['translation_revision']
    after, ty = changed_source(before), copy.deepcopy(tx)
    atom_id = next(node['ref'] for row in tx['results'] for node in row['target_inline'] if node['type'] == 'protected_ref')
    # Stored revision snapshots are authored specifically to isolate resolver
    # attribution; no parser/Provider/visual source certification is claimed.
    after['protected_atoms'][atom_id] = {**after['protected_atoms'][atom_id], 'value': '999'}
    for block in after['blocks']:
        block['source_hash'] = block_hash(block, after['protected_atoms'])
    seed(database, before, after, tx, ty)
    result = compare(client, tx['id'], ty['id'], 'target')
    assert result.status_code == 200, result.text
    expected = {row['block_id'] for row in tx['results'] if any(n.get('ref') == atom_id for n in row['target_inline'])}
    actual = {row['block_id'] for row in result.json()['changes'] if 'content' in row['aspects']}
    assert actual == expected


def test_source_image_content_changes_even_when_block_ast_and_asset_id_do_not(client, database):
    before = sample()['source_revision']
    after = changed_source(before)
    image = next(asset for asset in after['assets'] if asset['media_type'] == 'image/png')
    image['sha256'] = 'e'*64
    owner = next(b['id'] for b in after['blocks'] if b['attributes'].get('asset_id') == image['id'])
    seed(database, before, after)
    result = compare(client, before['id'], after['id'])
    assert result.status_code == 200, result.text
    row = next(row for row in result.json()['changes'] if row['block_id'] == owner)
    assert 'content' in row['aspects'] and row['kind'] == 'changed'
