"""Conservative diagnostics for newly introduced Hangul and kana in prose."""
import pytest

from packages.quality.scripts import unexpected_scripts


def test_reports_model_introduced_korean_number_words_with_occurrence_counts():
    assert unexpected_scripts('only one minibatch; at most one GPU',
        '只有 하나의小批量；하나의活跃小批量；最多 하나的 GPU', 'zh-Hans') == [
            {'script': 'Hangul', 'unexpected': [{'text': '하나의', 'count': 2}, {'text': '하나', 'count': 1}]}]


@pytest.mark.parametrize('locale,text', [
    ('ko', '하나의'), ('ko-KR', '하나의'), ('und-Hang', '하나의'),
    ('ja', 'ひとつ'), ('ja-JP', 'ひとつ'), ('und-Jpan', 'ひとつ'),
    ('zh-Hans', '一个 GPU 的 α 参数'), ('en', 'one GPU'),
])
def test_expected_script_and_scientific_notation_do_not_raise_findings(locale, text):
    assert unexpected_scripts('one GPU', text, locale) == []


def test_source_names_and_explicit_terms_are_allowed_without_hiding_new_words():
    assert unexpected_scripts('The 서울 and カナ models', '서울、カナ、하나의、小型ハナ模型',
        'zh-Hans', allowed_literals=['ハナ']) == [
            {'script': 'Hangul', 'unexpected': [{'text': '하나의', 'count': 1}]}]


def test_new_kana_is_visible_but_source_combining_spelling_is_equivalent():
    assert unexpected_scripts('Use カ\u3099', 'ガ、ひとつ', 'zh-Hant') == [
        {'script': 'Kana', 'unexpected': [{'text': 'ひとつ', 'count': 1}]}]


def test_retaining_one_name_does_not_allow_all_text_in_that_script():
    assert unexpected_scripts('서울', '서울 하나의', 'en')[0]['unexpected'] == [{'text': '하나의', 'count': 1}]


def test_explicit_latin_script_does_not_allow_hangul_for_romanized_korean():
    assert unexpected_scripts('one', '하나의', 'ko-Latn')[0]['script'] == 'Hangul'
