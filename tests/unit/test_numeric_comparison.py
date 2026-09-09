"""Numeric equivalence is mechanical and occurrence-aware, not semantic approval."""
import pytest

from packages.editorial.numbers import compare_numbers


@pytest.mark.parametrize('source,target', [
    ('up to 11 billion parameters', '最高达 110 亿参数'),
    ('3 billion parameters in total', '总参数量达到 30 亿'),
    ('131 . 4 k tokens/sec', '131.4 k tokens/秒'),
    ('1,024 and 1.5 million', '1024 和 150 万'),
    ('2.5 billion', '25亿'),
    ('-2.5 million', '−250万'),
    ('1e3 and 50%', '1000 和 ５０％'),
    ('16GB on TPUv3s', 'TPUv3 上的 16GB'),
    ('16, 64 and 128', '16、64、128'),
    ('0.1000', '0.1'),
    ('64, 128', '64，128'),
    ('1e999999 million', '10e999998 million'),
    ('1e999999999999999999999999', '1e999999999999999999999999'),
])
def test_equivalent_formats(source, target):
    assert compare_numbers(source, target)['matches']


@pytest.mark.parametrize('source,target', [
    ('64 tokens', '32 tokens'),
    ('11 billion', '11亿'),
    ('3 million', '30亿'),
    ('131 . 4 k', '131.5 k'),
    ('16, 64', '1664'),
    ('32 and 32', '32'),
    ('50%', '50'),
    ('-2.5 million', '250万'),
    ('1e3', '1e4'),
    ('0.123456789123456789', '0.123456789123456788'),
    ('1.\n2 items', '1.2 items'),
    ('1e999999999999999999999999', '1e999999999999999999999998'),
])
def test_real_mismatches_remain_blocking(source, target):
    assert not compare_numbers(source, target)['matches']


def test_evidence_explains_missing_and_extra_values_and_occurrences():
    evidence = compare_numbers('64 and 64; 3 billion', '64；30亿；32')
    assert not evidence['matches']
    assert evidence['missing_from_target'] == [{'value': '64', 'unit': '', 'count': 1}]
    assert evidence['extra_in_target'] == [{'value': '32', 'unit': '', 'count': 1}]
    assert {'text': '3 billion', 'value': '3000000000', 'unit': ''} in evidence['source_numbers']
    assert {'text': '30亿', 'value': '3000000000', 'unit': ''} in evidence['target_numbers']
