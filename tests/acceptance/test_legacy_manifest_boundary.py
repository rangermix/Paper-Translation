"""The release seed cannot detach a trusted file list from the bytes it imports."""
import copy
import json
from pathlib import Path

import pytest

from packages.domain.errors import DomainError
import packages.seed.legacy as legacy


@pytest.mark.parametrize('field,value', [
    ('html_path', 'fixtures/unknown-unreviewed.html'),
    ('source_path', '/tmp/unreviewed-source.pdf'),
])
def test_legacy_entry_paths_cannot_bypass_the_hashed_file_list(monkeypatch, field, value):
    # Synthetic in-memory release metadata: never change the reference package.
    frozen = (legacy.ROOT / 'reference/legacy-manifest.json').read_bytes()
    changed = copy.deepcopy(json.loads(frozen))
    changed['documents'][0][field] = value
    original = legacy.strict_loads
    monkeypatch.setattr(legacy, 'strict_loads', lambda content: changed if content == frozen else original(content))
    with pytest.raises(DomainError) as caught:
        legacy.checked_release()
    assert caught.value.code.startswith('LEGACY_')


def test_changed_legacy_html_bytes_are_rejected_without_touching_the_reference(tmp_path, monkeypatch):
    release = json.loads((legacy.ROOT / 'reference/legacy-manifest.json').read_bytes())
    entry = release['documents'][0]['files'][0]
    original_bytes = (legacy.ROOT / entry['path']).read_bytes()
    changed = tmp_path / 'changed-legacy.html'
    changed.write_bytes(original_bytes + b'\nChanged unreviewed bytes')
    original_safe_path = legacy.safe_path
    monkeypatch.setattr(legacy, 'safe_path', lambda root, relative, **kwargs:
        changed if str(relative) == entry['path'] else original_safe_path(root, relative, **kwargs))
    with pytest.raises(DomainError) as caught:
        legacy.checked_release()
    assert caught.value.code == 'LEGACY_HASH_MISMATCH'
    assert (legacy.ROOT / entry['path']).read_bytes() == original_bytes
