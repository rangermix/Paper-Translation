"""NB-AT05/06: counts describe page issues, with lossless diagnostic references."""
import copy

from packages.quality.issues import aggregate_source_issues, comparison_text


def test_missing_page_collapses_all_regions_without_losing_evidence():
    raw = [{'page': 14, 'code': 'SOURCE_PARSE_REVIEW', 'reason': 'Native text region not fully represented',
            'bbox': [10, i, 100, i + 1], 'text': str(i)} for i in range(174)]
    report = {'unresolved': raw, 'pages': [{'page': 14}], 'can_translate': False}
    source = {'blocks': []}
    before = copy.deepcopy(report)
    result = aggregate_source_issues(report, source)
    assert result['quality']['important'] == 1
    assert result['quality']['diagnostic_count'] == 174
    assert len(result['issues']) == 1
    assert result['issues'][0]['category'] == 'page_missing'
    assert result['issues'][0]['diagnostic_count'] == 174
    assert len(result['issues'][0]['evidence_refs']) == 174
    assert report == before
    assert result == aggregate_source_issues(report, source)


def test_adjacent_regions_merge_but_separate_columns_do_not():
    source = {'blocks': [{'id': 'b', 'provenance': [{'page': 5}]}]}
    raw = [{'page': 5, 'bbox': box, 'reason': 'Native text region not fully represented'}
           for box in ([10, 10, 100, 20], [10, 22, 100, 30], [200, 10, 300, 20])]
    result = aggregate_source_issues({'unresolved': raw}, source)
    assert len(result['issues']) == 2
    assert sum(r['diagnostic_count'] for r in result['issues']) == 3


def test_checking_failure_and_unchecked_do_not_look_like_no_issues():
    for state in ('not_checked', 'checking', 'stale', 'failed'):
        result = aggregate_source_issues({'check_state': state}, {'blocks': []})
        assert result['quality']['state'] == state
        assert result['quality']['blocking'] is False
    assert aggregate_source_issues({'unresolved': []}, {'blocks': []})['quality']['state'] == 'completed'


def test_comparison_normalizes_ligatures_wraps_and_footnote_marks_only():
    assert comparison_text('efﬁcient soft\u00adhyphen') == comparison_text('efficient softhyphen')
    assert comparison_text('trans-\nlation') == comparison_text('translation')
    assert comparison_text('Author†') == comparison_text('Author')
    assert comparison_text('9-5-1-1') != comparison_text('9.5-1-1')
    assert comparison_text('x²') != comparison_text('x2')
    assert comparison_text('x₂') != comparison_text('x2')
