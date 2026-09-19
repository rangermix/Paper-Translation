"""Immutable reader-v4 publication and self-contained offline export contracts."""
from copy import deepcopy
from pathlib import Path
import json
import re

from packages.ir import block_hash
from packages.editorial.drafts import render_input
from packages.publisher import Publisher, export_single_html


def fixture():
    ir=json.loads(Path('tests/fixtures/sample-document.json').read_text())
    source,tr=ir['source_revision'],ir['translation_revision']
    tr['content_policy']='nonblocking-v1'
    numeric=next(b for b in source['blocks'] if b['id']=='c2')
    numeric.update(raw_text='64',normalized_text='64',source_inline=[{'type':'text','text':'64'}])
    numeric['source_hash']=block_hash(numeric,source['protected_atoms'])
    next(r for r in tr['results'] if r['block_id']=='c2')['source_hash']=numeric['source_hash']
    equation=next(b for b in source['blocks'] if b['kind']=='math')
    equation['attributes'].update(representation='latex',equation_number='(3)')
    equation['source_hash']=block_hash(equation,source['protected_atoms'])
    next(r for r in tr['results'] if r['block_id']==equation['id'])['source_hash']=equation['source_hash']
    original=next(b for b in source['blocks'] if b['kind']=='reference')
    extra=deepcopy(original);extra.update(id='reference2',order=len(source['blocks']))
    extra['source_hash']=block_hash(extra,source['protected_atoms'])
    source['blocks'].append(extra);source['reading_order'].append(extra['id'])
    result=deepcopy(next(r for r in tr['results'] if r['block_id']==original['id']))
    result.update(block_id=extra['id'],source_hash=extra['source_hash']);tr['results'].append(result)
    return render_input(ir['document']['id'],source,tr,'reader-v4')


def test_math_equation_number_tables_and_bibliography_publish_as_whole_objects(tmp_path):
    ir=fixture();output=tmp_path/'reader'
    manifest=Publisher().build(ir,Path('tests'),output,include_source=True)
    html=(output/'index.html').read_text()
    assert 'data-tex=' in html and 'class="equation-number">(3)</span>' in html
    assert html.count('class="bibliography"')==1
    assert html.count('class="reference-entry"')==2
    assert 'class="figure-image"' in html
    cells=re.findall(r'<td\b.*?</td>',html,re.S)
    assert cells and all('<details' not in cell and 'class="label"' not in cell for cell in cells)
    assert 'class="cell-source"' in html and 'class="cell-target"' in html
    numeric=next(cell for cell in cells if '>64<' in cell)
    assert numeric.count('>64<')==1 and 'data-original-only="original_numeric_cell"' in numeric
    assert any(f['path']=='math.js' for f in manifest['files'])
    standalone=export_single_html(output,tmp_path/'reader.html',include_source=True).read_text()
    assert '<script src=' not in standalone
    assert 'katex' in standalone and 'script-src &#x27;self&#x27;' not in standalone
    assert len(re.findall(r"sha256-[A-Za-z0-9+/=]+",standalone))>=2
    assert 'Copyright (c) 2013-2020 Khan Academy' in standalone
    assert 'Permission is hereby granted, free of charge' in standalone


def test_older_table_asset_has_one_original_comparison(tmp_path):
    ir=fixture();source=ir['source_revision']
    table=next(b for b in source['blocks'] if b['kind']=='table')
    figure=next(b for b in source['blocks'] if b['kind']=='figure')
    table['attributes']['asset_id']=figure['attributes']['asset_id']
    table['attributes'].pop('comparison_asset_id',None)
    table['source_hash']=block_hash(table,source['protected_atoms'])
    next(r for r in ir['translation_revision']['results'] if r['block_id']==table['id'])['source_hash']=table['source_hash']
    ir=render_input(ir['document']['id'],source,ir['translation_revision'],'reader-v4')
    Publisher().build(ir,Path('tests'),tmp_path/'reader')
    text=(tmp_path/'reader/index.html').read_text()
    markup=re.search(r'<figure class="pair" id="b-'+table['id']+r'".*?</figure>',text,re.S).group()
    assert markup.count('class="original-comparison"')==1
    assert markup.count('<img')==1


def test_new_template_keeps_frozen_styles_and_legacy_render_behavior(tmp_path):
    from packages.templates.registry import get_template
    from packages.ir import digest
    for name in ['reader-v1','reader-v2','reader-v3']:
        t=get_template(name)
        assert digest(Path(t['css_path']).read_bytes())==t['css_sha256']
        assert digest(Path(t['js_path']).read_bytes())==t['js_sha256']
    ir=fixture();ir=render_input(ir['document']['id'],ir['source_revision'],ir['translation_revision'],'reader-v3')
    Publisher().build(ir,Path('tests'),tmp_path/'old')
    text=(tmp_path/'old/index.html').read_text()
    assert 'data-tex=' not in text and 'class="bibliography"' not in text
