import pytest

from packages.metadata.mapping import map_metadata, matches_paper


def test_crossref_requires_matching_doi_and_uses_publication_date_not_update():
    result = map_metadata({'DOI': '10.1234/Example', 'title': ['A <i>Research</i> Paper'],
        'author': [{'given': 'Alice', 'family': 'Example'}], 'container-title': ['Journal'],
        'published-print': {'date-parts': [[2020, 5]]}, 'published-online': {'date-parts': [[2019, 12, 31]]},
        'indexed': {'date-parts': [[2026]]}}, '10.1234/example', 'crossref')
    assert result['title'] == 'A Research Paper' and result['year'] == 2020
    assert result['date']['precision'] == 'month'
    assert result['authors'][0]['name'] == 'Alice Example'
    with pytest.raises(ValueError): map_metadata({'DOI': '10.1234/other', 'title': ['Other']}, '10.1234/example', 'crossref')


def test_csl_missing_fields_remain_null_and_active_markup_is_plain_text():
    result = map_metadata({'DOI': '10.1234/x', 'title': 'A <script>secret()</script><i>Paper</i>', 'issued': {'date-parts': [[2018]]}}, '10.1234/x', 'doi')
    assert result['title'] == 'A Paper'
    assert result['year'] == 2018 and result['container'] is None and result['authors'] == []
    assert result['date']['precision'] == 'year'


def test_first_page_title_and_author_cross_check_prevents_cited_paper_switch():
    found = {'title_hint': 'A Controlled Research Paper', 'author_hint': 'Alice Example',
        'header_text': 'A Controlled Research Paper Alice Example', 'selected': '10.1234/x',
        'candidates': [{'doi': '10.1234/x', 'confidence': 90, 'method': 'header'}]}
    right = map_metadata({'DOI': '10.1234/x', 'title': 'A Controlled Research Paper', 'author': [{'given': 'Alice', 'family': 'Example'}]}, '10.1234/x', 'doi')
    assert matches_paper(right, found)
    assert not matches_paper(right | {'title': 'Entirely unrelated scientific result'}, found)
    assert not matches_paper(right | {'authors': [{'name': 'Other Author', 'family': 'Author'}]}, found)
