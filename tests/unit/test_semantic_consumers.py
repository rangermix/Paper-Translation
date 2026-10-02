"""Schema 4.0 semantics survive real planner/correction/publisher boundaries."""
from copy import deepcopy
from pathlib import Path

import pytest
from lxml import html

from packages.ir import block_hash, canonical_bytes, digest, flatten_inline, validate_ir, validate_source
from packages.editorial.drafts import render_input, validate_target
from packages.translation.planner import plan_units, reassemble, cache_encode, cache_decode, cache_key
from tests.unit.test_parser_semantics import parse, document, layout
from tests.unit.test_translation import profile


def source(tmp_path):
    src=parse(document(layout('Text','<p>Some <b>important long words</b> H<sub>2</sub>O and <math>x&lt;y</math>. <a href="https://example.org">original label</a></p>')+layout('Table','<table><thead><tr><th id="a" scope="col">Header</th></tr></thead><tbody><tr><td headers="a"><p>A <i>cell</i></p><ul><li>Nested item</li></ul></td></tr></tbody></table>')),tmp_path)['source_revision']
    src['language']='en'
    for b in src['blocks']:b['language']='en'
    return src


def translate(src,limit=12):
    p=profile();p['max_unit_characters']=limit
    units=plan_units(src,'zh-Hans',p,nonblocking=True)
    translated={u['unit_id']:[{'type':'text','text':'译'+n['text']} if n['type']=='text' else deepcopy(n) for n in u['source_inline']] for u in units}
    return units,reassemble(units,translated),p


def test_formatting_link_labels_math_and_scripts_survive_splitting_and_cache(tmp_path):
    src=source(tmp_path);units,targets,p=translate(src)
    assert len(units)>5
    assert all(sum(len(n['text']) if n['type']=='text' else len(u['protected_atoms'][n['ref']]['value']) for n in u['source_inline'])<=12 for u in units)
    assert any('strong' in u.get('formatting_context',{}).get('marks',[]) for u in units)
    assert any(u.get('formatting_context',{}).get('href')=='https://example.org' for u in units)
    for bid,nodes in targets.items():validate_target(nodes,src,next(b for b in src['blocks'] if b['id']==bid))
    restored=[n for nodes in targets.values() for n in nodes]
    assert any(n['type']=='link' and n['href']=='https://example.org' and n['text'].startswith('译') for n in restored)
    assert any(n['type']=='protected_ref' and n.get('marks')==['subscript'] for n in restored)
    assert any(n.get('marks')==['strong'] and n['text'].startswith('译') for n in restored if n['type']=='text')
    for u in units:assert cache_decode(u,cache_encode(u,u['source_inline']))==u['source_inline']
    styled=next(u for u in units if u.get('formatting_context',{}).get('marks'))
    plain=deepcopy(styled);plain['formatting_context']={}
    assert cache_key(styled,p,'empty')!=cache_key(plain,p,'empty')


def test_text_only_local_transport_returns_styled_scientific_nodes(tmp_path):
    from packages.providers.local_translation import source_text, target_inline
    src=source(tmp_path);units,_,_=translate(src,2000)
    styled=next(u for u in units if u.get('formatting_context',{}).get('marks'))
    text,_=source_text(styled)
    restored=target_inline('译'+text,styled)
    from packages.translation.planner import restore_inline
    result=restore_inline(styled,restored)
    assert any(n.get('marks')==styled['formatting_context']['marks'] for n in result)


def render_snapshot(src):
    units,targets,_=translate(src,2000)
    from packages.ir.retention import original_only_blocks
    retained=original_only_blocks(src)
    results=[]
    for b in src['blocks']:
        nodes=targets.get(b['id'],[])
        reason=retained.get(b['id']) or ('structural_container' if b['attributes'].get('children_block_ids') or b['kind'] in {'table','group'} else 'original_'+b['kind'])
        if not b['normalized_text'] and any(n['type']=='protected_ref' and src['protected_atoms'][n['ref']]['kind']=='control' for n in b['source_inline']):reason='static_control'
        results.append({'block_id':b['id'],'source_hash':b['source_hash'],'context_hash':'a'*64,'status':'translated' if nodes else 'retained','target_inline':nodes,
            'warnings':[],'review_state':'not_reviewed','reason':'' if nodes else reason,'review_record':None,
            'generation':{'kind':'model' if nodes else 'retained','provider':'fixture','model':'offline-double','profile_version':'fixture-v1','prompt_version':'fixture-v1','glossary_revision':'empty-v1','attempt_id':None}})
    title=flatten_inline(targets.get(src['title_block_id'],[]),src['protected_atoms']) or next(b['normalized_text'] for b in src['blocks'] if b['id']==src['title_block_id'])
    translation={'id':'translation-rich','source_revision_id':src['id'],'target_language':'zh-Hans','title':title,'profile_version':'fixture-v1','glossary_revision':'empty-v1',
        'engine':{'kind':'model','provider':'fixture','model':'offline-double','prompt_version':'fixture-v1'},'sealed_at':'2026-10-02T00:00:00Z','results':results,'content_policy':'nonblocking-v1'}
    return render_input('document-rich',src,translation)


def test_rich_reader_and_offline_export_preserve_structure_and_escape_auxiliary(tmp_path):
    from packages.publisher import Publisher, export_single_html, export_bundle, verify_artifact
    src=source(tmp_path);ir=render_snapshot(src);validate_ir(ir,asset_root=tmp_path)
    assert ir['schema_version']=='4.0' and ir['render']['template_id']=='reader-v10'
    from packages.domain.errors import DomainError
    with pytest.raises(DomainError) as error:render_input('doc',src,ir['translation_revision'],'reader-v9')
    assert error.value.code == 'TEMPLATE_SCHEMA_INCOMPATIBLE'
    artifact=tmp_path/'published';Publisher().build(ir,tmp_path,artifact,include_source=True)
    verify_artifact(artifact)
    tree=html.fromstring((artifact/'index.html').read_bytes())
    assert tree.xpath('//sub') and tree.xpath('//strong')
    assert tree.xpath('//span[@data-tex="x<y"]')
    assert tree.xpath('//th[@scope="col"]') and tree.xpath('//td[@headers]')
    assert tree.xpath('//thead') and tree.xpath('//tbody') and tree.xpath('//table//ul//li')
    assert tree.xpath('//a[@href="https://example.org"]')
    assert not tree.xpath('//script[not(@src)]|//input|//iframe')
    export_single_html(artifact,tmp_path/'offline.html');export_bundle(artifact,tmp_path/'offline.zip')
    assert 'x&lt;y' in (tmp_path/'offline.html').read_text() and (tmp_path/'offline.zip').stat().st_size>0
    original=(artifact/'index.html').read_bytes()
    assert digest(original)==next(f['sha256'] for f in verify_artifact(artifact)['files'] if f['path']=='index.html')


def test_source_correction_preserves_marks_and_recursive_order(tmp_path):
    from packages.source_revisions.corrections import replacement_inline,_set_order
    src=source(tmp_path);validate_source(src,asset_root=tmp_path)
    b=next(b for b in src['blocks'] if b['kind']=='paragraph' and 'important' in b['normalized_text'])
    runs=[{'type':'text','text':'wrd','marks':['strong']}]
    restored=replacement_inline(src,b,runs,'word')
    assert ''.join(n['text'] for n in restored)=='word' and all(n['marks']==['strong'] for n in restored)
    before={b['id'] for b in src['blocks']}
    _set_order(src,list(reversed(src['reading_order'])))
    assert {b['id'] for b in src['blocks']}==before
    validate_source(src,asset_root=tmp_path)


def test_marks_and_ownership_cycles_are_validated(tmp_path):
    src=source(tmp_path);bad=deepcopy(src)
    b=next(b for b in bad['blocks'] if b['source_inline']);b['source_inline'][0]['marks']=['onclick'];b['source_hash']=block_hash(b,bad['protected_atoms'])
    with pytest.raises(ValueError):validate_source(bad)


def test_reader_note_anchors_are_unique_inside_compound_layout(tmp_path):
    from packages.publisher.renderer import render_html
    raw=document(layout('Text','<p>Body <a href="#note"><sup>1</sup></a>.</p>')+layout('Footnote','<p id="note">First printed note.</p><p>Second printed note.</p>'))
    src=parse(raw,tmp_path)['source_revision'];ir=render_snapshot(src)
    tree=html.fromstring(render_html(ir,{a['id']:a['storage_key'] for a in src['assets']}))
    ids=tree.xpath('//@id');assert len(ids)==len(set(ids))
    refs=tree.xpath('//a[@role="doc-noteref"]/@href');assert refs
    assert all(tree.xpath('//*[@id=$id]',id=href[1:]) for href in refs)
    bad=deepcopy(src);group=next(b for b in bad['blocks'] if b['kind']=='group');group['owner_id']=group['id']
    with pytest.raises(ValueError):validate_source(bad)


def test_empty_static_control_can_publish_without_fabricated_translation(tmp_path):
    from packages.publisher import Publisher
    src=parse(document(layout('Form','<p><input type="text" value=""></p>')),tmp_path)['source_revision']
    ir=render_snapshot(src);validate_ir(ir,asset_root=tmp_path)
    retained=next(r for r in ir['translation_revision']['results'] if r['reason']=='static_control')
    assert retained['status']=='retained' and retained['generation']['kind']=='retained' and not retained['target_inline']
    Publisher().build(ir,tmp_path,tmp_path/'published',include_source=True)
    tree=html.fromstring((tmp_path/'published/index.html').read_bytes())
    assert tree.xpath('//span[@data-kind="control"]') and not tree.xpath('//input')
