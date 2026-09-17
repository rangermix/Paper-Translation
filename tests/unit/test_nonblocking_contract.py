"""NB-AT02: explicit partial results retain strict render input safety."""
import copy
import json
from pathlib import Path

import pytest

from packages.ir import IRValidationError, validate_ir


def partial_ir():
    value = json.loads(Path('fixtures/sample-document-v3.json').read_text('utf-8'))
    value['translation_revision']['content_policy'] = 'nonblocking-v1'
    result = value['translation_revision']['results'][1]
    result.update(status='fallback', target_inline=[], reason='translation_unavailable',
                  fallback={'mode': 'source_text'}, review_state='not_reviewed', review_record=None)
    return value


def test_explicit_fallback_can_be_released_without_claiming_translation():
    value = partial_ir()
    assert validate_ir(value) is value
    assert value['translation_revision']['results'][1]['target_inline'] == []


@pytest.mark.parametrize('mutation', [
    lambda v: v['translation_revision']['results'][1].update(target_inline=[{'type': 'html', 'html': '<script>1</script>'}]),
    lambda v: v['source_revision']['assets'][0].update(storage_key='../outside.pdf'),
    lambda v: v['translation_revision']['results'][1].update(target_inline=[{'type': 'text', 'text': 'fake translation'}]),
    lambda v: v['translation_revision']['results'][1].update(reason=''),
    lambda v: v['translation_revision']['results'][1]['fallback'].update(mode='remote_url', url='https://example.org'),
    lambda v: v['translation_revision'].pop('content_policy'),
])
def test_partial_result_does_not_relax_ast_paths_or_truthfulness(mutation):
    value = partial_ir()
    mutation(value)
    with pytest.raises(IRValidationError):
        validate_ir(value)


def test_quality_failure_is_independent_of_execution_permission():
    from packages.domain.workflow import QualitySummary
    for state in ('not_checked', 'checking', 'completed', 'stale', 'failed'):
        summary = QualitySummary(state=state, important=174)
        assert summary.model_dump()['blocking'] is False


def test_nb_acceptance_registry_is_complete_and_acyclic():
    backlog = json.loads(Path('docs/contracts/nonblocking-workflow-backlog.json').read_text('utf-8'))
    seen = set()
    for task in backlog['tasks']:
        assert set(task['depends_on']) <= seen
        seen.add(task['id'])
    assert len(seen) == 12
    assert {a for t in backlog['tasks'] for a in t['acceptance']} == {f'NB-AT{i:02}' for i in range(1, 25)}
