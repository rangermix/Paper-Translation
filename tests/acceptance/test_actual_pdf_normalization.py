"""M0-AT05A: real PDF glyph extraction, traceable mechanical source edits.

This controlled PDF has a real /fi glyph with an explicit U+FB01 ToUnicode map.
It tests native extraction and normalization, not a model's layout capability.
"""
import copy
import json
from pathlib import Path

from packages.ir import block_hash,canonical_bytes,digest,validate_source
from packages.parsers import inspect_pdf
from packages.source_revisions import apply_corrections

ROOT=Path(__file__).resolve().parents[2]


def make_pdf(path):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,ArrayObject,NumberObject,DecodedStreamObject
    writer=PdfWriter();page=writer.add_blank_page(612,792)
    cmap=DecodedStreamObject()
    mapping='\n'.join(f'<{cp:02X}> <{0xfb01 if cp==70 else cp:04X}>' for cp in range(32,127))
    cmap.set_data(('/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n/CMapName /NativeFixture def /CMapType 2 def\n1 begincodespacerange <00> <FF> endcodespacerange\n95 beginbfchar\n'+mapping+'\nendbfchar endcmap CMapName currentdict /CMap defineresource pop end end').encode())
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Times-Roman'),
        NameObject('/Encoding'):DictionaryObject({NameObject('/Type'):NameObject('/Encoding'),NameObject('/BaseEncoding'):NameObject('/WinAnsiEncoding'),NameObject('/Differences'):ArrayObject([NumberObject(70),NameObject('/fi')])}),NameObject('/ToUnicode'):writer._add_object(cmap)})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 18 Tf 55 710 Td (Normalization source) Tj 0 -50 Td (The ofFce trans-) Tj 0 -24 Td (former is safe.) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream)
    with path.open('wb') as handle:writer.write(handle)


def test_original_pdf_ligature_and_wrapped_word_have_replayable_raw_intervals(tmp_path):
    import pypdfium2 as pdfium
    output=ROOT/'.agent/tmp/evidence/native-normalization-at05a';output.mkdir(parents=True,exist_ok=True)
    pdf=tmp_path/'original.pdf';make_pdf(pdf);original=pdf.read_bytes();before=digest(original)
    inspection=inspect_pdf(pdf);regions=inspection['pages'][0]['text_regions']
    title=next(r for r in regions if 'Normalization' in r['text'])
    body=[r for r in regions if 'office' in r['text'] or 'former is safe.' in r['text']]
    assert len(body)==2
    # PDFium expands ligatures and reports discretionary hyphen as U+0002;
    # pypdf preserves the PDF's ToUnicode raw glyph mapping for this contract.
    from pypdf import PdfReader,__version__
    raw='\n'.join(PdfReader(pdf).pages[0].extract_text().splitlines()[1:])
    assert raw=='The ofﬁce trans-\nformer is safe.'
    normalized='The office transformer is safe.'
    asset_id='native-pdf'
    def block(bid,text,selected,kind):
        return {'id':bid,'kind':kind,'order':0 if kind=='heading' else 1,'parent_id':None if kind=='heading' else 'title','owner_id':None,
            'language':'en','translatable':True,'raw_text':text,'normalized_text':text,'normalization_edits':[],
            'source_inline':[{'type':'text','text':text}],'warnings':[],'attributes':{'level':1} if kind=='heading' else {},
            'provenance':[{'type':'pdf','asset_id':asset_id,'page':1,'bbox':r['bbox'],'coordinate_system':'top-left-points','page_size':[612,792]} for r in selected]}
    blocks=[block('title',title['text'],[title],'heading'),block('body',raw,body,'paragraph')]
    for b in blocks:b['source_hash']=block_hash(b,{})
    source={'id':'source-native-normalization','kind':'pdf_upload','language':'en','original_asset_id':asset_id,'sha256':before,
        'created_at':'2026-09-06T00:00:00Z','parser':{'name':'pypdf-raw-pdfium-locators-contract','version':__version__,'config_hash':digest({})},
        'normalization_version':'identity-v1','title_block_id':'title','reading_order':['title','body'],'protected_atoms':{},'blocks':blocks,
        'assets':[{'id':asset_id,'media_type':'application/pdf','sha256':before,'storage_key':'original.pdf','byte_size':len(original)}]}
    validate_source(source,asset_root=tmp_path);source_before=copy.deepcopy(source)
    proof={'page':1,'bbox':body[0]['bbox'],'quote':raw}
    result=apply_corrections(source,[{'kind':'replace_text','block_id':'body','start':0,'end':len(raw),'text':normalized}],proof,
        'Native /fi glyph expands U+FB01; original visible line-end hyphen joins trans- plus former. Keep the raw Unicode offsets and original PDF.')
    changed=next(b for b in result['source']['blocks'] if b['id']=='body')
    assert source==source_before and changed['raw_text']==raw
    replay=raw
    for edit in reversed(changed['normalization_edits']):replay=replay[:edit['raw_start']]+edit['replacement']+replay[edit['raw_end']:]
    assert replay==normalized==changed['normalized_text']
    assert changed['provenance']==blocks[1]['provenance']
    assert pdf.read_bytes()==original and digest(pdf.read_bytes())==before
    validate_source(result['source'],asset_root=tmp_path)
    with pdfium.PdfDocument(pdf) as doc:
        page=doc[0];bitmap=page.render(scale=1.5);bitmap.to_pil().save(output/'page-1.png');bitmap.close();page.close()
    (output/'original.pdf').write_bytes(original)
    (output/'source-before.json').write_bytes(canonical_bytes(source))
    (output/'source-after.json').write_bytes(canonical_bytes(result['source']))
    (output/'inspection.json').write_text(json.dumps(inspection,ensure_ascii=False,indent=2),encoding='utf8')
    (output/'verification.json').write_text(json.dumps({'scenario':'M0-AT05A','execution':'real native PDF extraction and mechanical correction; no Docling/model inference',
        'original_pdf_sha256_before':before,'original_pdf_sha256_after':digest(pdf.read_bytes()),'raw_text':raw,'normalized_text':normalized,
        'normalization_edits':changed['normalization_edits'],'original_provenance':changed['provenance'],'raw_edit_replay_exact':True},ensure_ascii=False,indent=2),encoding='utf8')
