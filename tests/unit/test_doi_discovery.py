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
