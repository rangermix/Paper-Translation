import copy
import os
import subprocess
import sys

import pytest

from packages.ir import block_hash, digest


def paper():
    rows = [
        ('title', 'title', None, 'Parallel systems and matrices'),
        ('abstract', 'heading', 'title', 'Abstract'),
        ('overview', 'paragraph', 'abstract', 'We study pipeline parallelism and matrix decomposition. Our contribution is a bounded scheduling method.'),
        ('systems', 'heading', 'title', 'Process scheduling'),
        ('def1', 'paragraph', 'systems', 'We define rank as the identifier of a process. Pipeline parallelism assigns stages to ranks.'),
        ('use1', 'paragraph', 'systems', 'Each rank sends pipeline parallelism messages to the next process.'),
        ('matrices', 'heading', 'title', 'Matrix algebra'),
        ('def2', 'paragraph', 'matrices', 'We define rank as the number of independent matrix columns.'),
        ('use2', 'paragraph', 'matrices', 'The rank determines the decomposition.'),
        ('abbr', 'paragraph', 'systems', 'Data parallelism (DP) replicates workers. DP exchanges gradients.'),
        ('conclusion', 'heading', 'title', 'Conclusion'),
        ('end', 'paragraph', 'conclusion', 'The scheduler reduces communication without changing convergence.'),
        ('refs', 'reference', None, 'A. Author. Rank scheduling survey. 2025.'),
    ]
    blocks = []
    for order, (bid, kind, parent, text) in enumerate(rows):
        block = {'id': bid, 'kind': kind, 'parent_id': parent, 'order': order,
                 'normalized_text': text, 'source_inline': [{'type': 'text', 'text': text}],
                 'translatable': kind != 'reference', 'language': 'en', 'attributes': {}}
        block['source_hash'] = block_hash(block, {})
        blocks.append(block)
    return {'id': 'source-v1', 'language': 'en', 'title_block_id': 'title',
            'normalization_version': 'test-v1', 'blocks': blocks, 'protected_atoms': {}}


def test_collection_is_grounded_deterministic_and_never_mutates_source():
    from packages.preparation.collection import collect
    source = paper()
    before = copy.deepcopy(source)
    pack = collect(source)
    assert source == before and pack == collect(source)
    assert pack['source_hash'] == digest(source)
    by = {b['id']: b for b in source['blocks']}
    assert {'abstract', 'contribution', 'definition', 'conclusion'} <= {e['role'] for e in pack['evidence']}
    assert all(e['quote'] in by[e['block_id']]['normalized_text'] for e in pack['evidence'])
    assert all(e['block_id'] != 'refs' for e in pack['evidence'])
    assert pack['coverage']['scanned_blocks'] == len(source['blocks'])


def test_defined_rare_senses_and_acronym_are_retained():
    from packages.preparation.collection import collect
    pack = collect(paper())
    ranks = [c for c in pack['concepts'] if c['source'].casefold() == 'rank']
    assert len(ranks) == 2
    assert {c['scope'] for c in ranks} == {'systems', 'matrices'}
    assert ranks[0]['id'] != ranks[1]['id']
    assert any(c['source'] == 'Data parallelism' and 'DP' in c['aliases'] for c in pack['concepts'])


def test_context_selects_sense_and_existing_glossary_wins():
    from packages.preparation.collection import collect
    from packages.preparation.context import freeze, select_context
    source = paper()
    pack = collect(source)
    proposals = {c['id']: ('进程编号' if c['scope'] == 'systems' else '秩')
                 for c in pack['concepts'] if c['source'] == 'rank'}
    prepared = freeze(pack, 'zh-Hans', 'empty-v1', [], proposals=proposals)
    one = select_context(prepared, source, 'use1', 'Each rank sends messages.')
    two = select_context(prepared, source, 'use2', 'The rank determines the decomposition.')
    assert [e['target'] for e in one['glossary'] if e['source'] == 'rank'] == ['进程编号']
    assert [e['target'] for e in two['glossary'] if e['source'] == 'rank'] == ['秩']
    explicit = {'source': 'rank', 'target': '用户选择', 'mode': 'must'}
    prepared2 = freeze(pack, 'zh-Hans', 'manual-v1', [explicit], proposals=proposals)
    assert select_context(prepared2, source, 'use1', 'Each rank')['glossary'] == [explicit]
    assert prepared['revision'] != prepared2['revision']
    assert select_context(prepared, source, 'end', 'Communication')['glossary'] == []


def test_evidence_and_context_bounds_are_visible():
    from packages.preparation.collection import collect
    from packages.preparation.context import freeze, select_context
    from packages.ir import canonical_bytes
    source = paper()
    pack = collect(source, max_evidence=3, max_concepts=2)
    assert len(pack['evidence']) <= 3 and len(pack['concepts']) <= 2
    assert pack['coverage']['omitted_evidence'] > 0
    prepared = freeze(pack, 'zh-Hans', 'empty-v1', [])
    context = select_context(prepared, source, 'use1', 'Each rank', max_bytes=240)
    assert len(canonical_bytes(context)) <= 240
    assert context['omitted'] > 0


def test_unresolved_concepts_remain_unreviewed_without_invented_targets():
    from packages.preparation.collection import collect
    from packages.preparation.context import freeze
    prepared = freeze(collect(paper()), 'zh-Hant', 'empty-v1', [])
    assert prepared['target_locale'] == 'zh-Hant'
    assert prepared['concepts']
    assert all(c['review_status'] == 'not_reviewed' for c in prepared['concepts'])
    assert all(c.get('target') is None for c in prepared['concepts'])


def test_hashes_are_stable_between_worker_processes():
    command = [sys.executable, '-c', 'from test_preparation import paper; from packages.preparation.collection import collect; print(collect(paper())["revision"])']
    env = {**os.environ, 'PYTHONPATH': 'src:tests/unit'}
    first = subprocess.check_output(command, env={**env, 'PYTHONHASHSEED': '1'})
    second = subprocess.check_output(command, env={**env, 'PYTHONHASHSEED': '2'})
    assert first == second


def test_conflicting_definitions_in_one_section_stay_unresolved():
    from packages.preparation.collection import collect
    from packages.preparation.context import freeze, select_context
    source = paper()
    next(b for b in source['blocks'] if b['id'] == 'def2')['parent_id'] = 'systems'
    pack = collect(source)
    ranks = [c for c in pack['concepts'] if c['source'] == 'rank']
    assert len(ranks) == 2 and {c['scope'] for c in ranks} == {'systems'}
    prepared = freeze(pack, 'zh-Hans', 'empty-v1', [], proposals={ranks[0]['id']: '编号', ranks[1]['id']: '秩'})
    selected = select_context(prepared, source, 'use1', 'Each rank')
    assert selected['glossary'] == [] and selected['omitted'] > 0


def test_definition_has_priority_over_a_large_generated_summary():
    from packages.preparation.collection import collect
    from packages.preparation.context import freeze, select_context
    source = paper()
    pack = freeze(collect(source), 'zh-Hans', 'empty-v1', [], summary=[{'text': 'long summary ' * 500, 'evidence_ids': []}])
    selected = select_context(pack, source, 'use1', 'Each rank', max_bytes=800)
    assert any('identifier of a process' in e['quote'] for e in selected['evidence'])


def test_phrase_statistics_do_not_join_across_punctuation_or_digits():
    from packages.preparation.collection import collect
    source = paper()
    for bid in ('use1', 'use2'):
        next(b for b in source['blocks'] if b['id'] == bid)['normalized_text'] = 'Spectral, topology. Spectral 2 topology.'
    assert not any(c['source'].casefold() == 'spectral topology' for c in collect(source)['concepts'])


def test_long_passages_are_not_silently_cut_and_chinese_sentences_split():
    from packages.preparation.collection import collect
    source = paper()
    block = next(b for b in source['blocks'] if b['id'] == 'def1')
    block['normalized_text'] = 'We define rank as ' + 'a property ' * 100 + 'only for a matrix, never for a process.'
    other = next(b for b in source['blocks'] if b['id'] == 'overview')
    other['normalized_text'] = '我们定义秩为独立列的数量。此定义仅用于矩阵。'
    pack = collect(source)
    assert not any(e['block_id'] == 'def1' for e in pack['evidence'])
    assert pack['coverage']['omitted_evidence'] > 0
    assert any(e['quote'] == '此定义仅用于矩阵。' for e in pack['evidence'])


def test_context_rejects_impossible_budget():
    from packages.preparation.collection import collect
    from packages.preparation.context import freeze, select_context
    with pytest.raises(ValueError, match='CONTEXT_BUDGET'):
        select_context(freeze(collect(paper()), 'zh-Hans', 'empty-v1', []), paper(), 'use1', 'rank', max_bytes=10)


def test_shared_acronym_keeps_section_specific_meaning():
    from packages.preparation.collection import collect
    from packages.preparation.context import freeze, select_context
    source = paper()
    other = next(b for b in source['blocks'] if b['id'] == 'def2')
    other['normalized_text'] = 'Dynamic programming (DP) solves this problem.'
    pack = collect(source)
    concepts = [c for c in pack['concepts'] if 'DP' in c['aliases']]
    assert {c['scope'] for c in concepts} == {'systems', 'matrices'}
    prepared = freeze(pack, 'zh-Hans', 'empty-v1', [], proposals={c['id']: c['source'] for c in concepts})
    targets = select_context(prepared, source, 'use1', 'DP sends data')['glossary']
    concept = next(c for c in concepts if c['scope'] == 'systems')
    assert targets == [{'source': 'DP', 'target': 'Data parallelism', 'mode': 'preferred',
                        'concept_id': concept['id'], 'scope': 'systems', 'evidence_ids': concept['evidence_ids'], 'origin': 'model',
                        'note': 'Model suggestion; verify against source definition.'}]
