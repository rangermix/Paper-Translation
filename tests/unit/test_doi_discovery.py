import pytest

from packages.metadata.discovery import discover_doi, normalize_doi


def page(text, number=1):
    return {'page': number, 'page_size': [600, 800], 'text_regions': [{'text': text, 'bbox': [40, 40, 560, 150]}], 'links': []}


def test_normalization_keeps_balanced_legal_suffix_and_decodes_prefix():
    assert normalize_doi('https://doi.org/10.1000%2Fabc(12).') == '10.1000/abc(12)'
    assert normalize_doi('doi: 10.1234/a;b(2)') == '10.1234/a;b(2)'
    assert normalize_doi('10.1234/\nwrapped') == '10.1234/wrapped'
    assert normalize_doi('https://attacker.test/10.1234/x') is None


def test_header_doi_outranks_reference_and_persists_both_evidence():
    found = discover_doi({}, [page('A Controlled Research Paper\nAlice Example\ndoi:10.1234/own\nAbstract\nText\nReferences\n[1] doi:10.1234/cited')])
    assert found['selected'] == '10.1234/own'
    assert {c['doi'] for c in found['candidates']} == {'10.1234/own', '10.1234/cited'}
    cited = next(c for c in found['candidates'] if c['doi'].endswith('cited'))
    assert cited['reference'] is True


def test_ambiguous_header_dois_never_choose_first():
    found = discover_doi({}, [page('doi:10.1234/one\ndoi:10.1234/two')])
    assert found['status'] == 'ambiguous' and found['selected'] is None


def test_reference_only_and_no_doi_keep_no_selected_identifier():
    assert discover_doi({}, [page('References\n[1] doi:10.1234/cited')])['selected'] is None
    assert discover_doi({}, [page('No identifier in this paper')])['status'] == 'no_doi'


def test_embedded_doi_and_xmp_are_discovered_without_full_vlm_parse():
    metadata = {'/Title': 'A Controlled Research Paper', '/Author': 'Alice Example'}
    xmp = '<rdf><identifier>https://doi.org/10.1234/embedded</identifier></rdf>'
    found = discover_doi(metadata, [], xmp=xmp)
    assert found['selected'] == '10.1234/embedded'
    assert found['title_hint'] == 'A Controlled Research Paper'
    assert found['candidates'][0]['method'] == 'xmp'


def test_first_page_prominent_title_is_available_without_embedded_metadata():
    regions = [
        {'text': 'A Controlled Research Paper', 'bbox': [40, 60, 550, 80]},
        {'text': 'about Reliable Metadata', 'bbox': [40, 89, 550, 104]},
        {'text': 'Alice Example', 'bbox': [40, 120, 300, 130]},
        {'text': 'Abstract', 'bbox': [40, 160, 200, 172]},
        {'text': 'Private body text must not become search terms.', 'bbox': [40, 180, 550, 192]},
    ]
    found = discover_doi({'/Title': 'main.pdf'}, [{'page': 1, 'page_size': [600, 800],
        'text_regions': regions, 'links': []}])
    assert found['selected'] is None
    assert found['title_hint'] == 'A Controlled Research Paper about Reliable Metadata'
    assert found['title_method'] == 'first_page_heading'


def test_body_and_reference_pages_are_not_guessed_as_titles():
    found = discover_doi({}, [page('Abstract\nPrivate study contents\nReferences\nA Cited Paper')])
    assert not found['title_hint']


@pytest.mark.parametrize('first,last', [('Learning to Represent', 'Networks'),
    ('Learning', 'Representations of Complex Networks')])
def test_short_lines_are_preserved_in_a_wrapped_paper_title(first, last):
    found = discover_doi({}, [{'page': 1, 'page_size': [600, 800], 'text_regions': [
        {'text': first, 'bbox': [40, 60, 550, 80]},
        {'text': last, 'bbox': [40, 84, 550, 104]},
        {'text': 'Alice Example', 'bbox': [40, 120, 300, 130]},
        {'text': 'Abstract', 'bbox': [40, 160, 200, 172]},
        {'text': 'Body text follows.', 'bbox': [40, 180, 550, 192]},
    ]}])
    assert found['title_hint'] == first + ' ' + last


@pytest.mark.parametrize('title', ['Abstract Interpretation: A Unified Lattice Model for Static Analysis',
    'Introduction to Quantum Information Theory'])
def test_titles_starting_with_section_words_are_kept(title):
    assert discover_doi({'/Title': title}, [])['title_hint'] == title
    found = discover_doi({}, [{'page': 1, 'page_size': [600, 800], 'text_regions': [
        {'text': title, 'bbox': [40, 60, 550, 80]},
        {'text': 'Alice Example', 'bbox': [40, 120, 300, 130]},
        {'text': 'Abstract', 'bbox': [40, 160, 200, 172]},
        {'text': 'Body text follows.', 'bbox': [40, 180, 550, 192]},
    ]}])
    assert found['title_hint'] == title
    found = discover_doi({}, [page('A title on page two', number=2)])
    assert not found['title_hint']


@pytest.mark.parametrize('stamp,doi', [
    ('arXiv:1806.03377v1 [cs.DC] 8 Jun 2018', '10.48550/arxiv.1806.03377'),
    ('arXiv:2301.12345v12 [cs.LG] 31 Jan 2023', '10.48550/arxiv.2301.12345'),
    ('arXiv:hep-th/9901001v2 8 Jan 1999', '10.48550/arxiv.hep-th/9901001'),
    ('arXiv:math.CA/0611800v2 8 Nov 2006', '10.48550/arxiv.math/0611800'),
])
def test_first_page_arxiv_stamp_identifies_the_preprint(stamp, doi):
    found = discover_doi({'/Title': 'PipeDream: Fast and Efficient Pipeline Parallel DNN Training -0.22in',
        '/Author': 'Amar Phanishayee'}, [page('PipeDream: Fast and Efficient Pipeline Parallel DNN Training\n'
        'Aaron Harlap, Deepak Narayanan, Amar Phanishayee\n' + stamp + '\nAbstract\nTraining contents.')])
    assert found['selected'] == doi
    assert found['status'] == 'found'
    assert found['candidates'][0]['method'] == 'arxiv_header'
    assert found['candidates'][0]['page'] == 1


@pytest.mark.parametrize('text,number', [
    ('Abstract\nWe compare to arXiv:1806.03377v1.', 1),
    ('Abstract\narXiv:1806.03377v1 [cs.DC] 8 Jun 2018', 1),
    ('Abstract: We compare prior work.\narXiv:1806.03377v1', 1),
    ('Abstract—We compare prior work.\narXiv:1806.03377v1', 1),
    ('Abstract We compare prior work.\narXiv:1806.03377v1', 1),
    ('References\narXiv:1806.03377v1 [cs.DC] 8 Jun 2018', 1),
    ('1 Introduction\narXiv:1806.03377v1', 1),
    ('1. Introduction\narXiv:1806.03377v1', 1),
    ('1.1 Introduction\narXiv:1806.03377v1', 1),
    ('7 References\narXiv:1806.03377v1', 1),
    ('I. INTRODUCTION\narXiv:1806.03377v1', 1),
    ('I INTRODUCTION\narXiv:1806.03377v1', 1),
    ('VII. REFERENCES\narXiv:1806.03377v1', 1),
    ('See the related preprint arXiv:1806.03377v1', 1),
    ('arXiv:1806.03377v1 [cs.DC] 8 Jun 2018', 2),
    ('arXiv:1813.03377v1', 1),
    ('arXiv:1806.033777v1', 1),
    ('arXiv:1806.03377v0', 1),
])
def test_arxiv_citations_and_invalid_identifiers_do_not_identify_the_paper(text, number):
    found = discover_doi({}, [page(text, number)])
    assert found['selected'] is None


def test_conflicting_arxiv_stamps_are_ambiguous():
    found = discover_doi({}, [page('arXiv:1806.03377v1\narXiv:2301.12345v2\nAbstract')])
    assert found['status'] == 'ambiguous'
    assert found['selected'] is None


def test_explicit_publication_doi_takes_precedence_over_arxiv_stamp():
    found = discover_doi({}, [page('arXiv:1806.03377v1\ndoi:10.1145/3341301.3359646\nAbstract')])
    assert found['selected'] == '10.1145/3341301.3359646'
    assert {c['doi'] for c in found['candidates']} == {
        '10.48550/arxiv.1806.03377', '10.1145/3341301.3359646'}


def test_body_doi_citation_does_not_override_the_arxiv_stamp():
    found = discover_doi({}, [page('arXiv:1806.03377v1\nAbstract\nWe compare doi:10.1234/other')])
    assert found['selected'] == '10.48550/arxiv.1806.03377'


def test_second_page_doi_does_not_override_the_arxiv_stamp():
    found = discover_doi({}, [page('arXiv:1806.03377v1\nAbstract'), page('doi:10.1234/other', 2)])
    assert found['selected'] == '10.48550/arxiv.1806.03377'


@pytest.mark.parametrize('title', ['Introduction to Quantum Information Theory',
    'Abstract Interpretation: A Unified Lattice Model for Static Analysis'])
def test_arxiv_stamp_after_a_title_starting_with_section_words_is_kept(title):
    found = discover_doi({'/Title': title}, [page(title + '\nAlice Example\narXiv:2301.12345v1\nAbstract')])
    assert found['selected'] == '10.48550/arxiv.2301.12345'
