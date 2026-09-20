"""Docling adapter with independent native coverage accounting and local assets."""
from __future__ import annotations

import os
import re
import shutil
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from packages.ir import block_hash, canonical_bytes, digest, validate_source
from .inspect import PDFError, inspect_pdf
from .models import verify_models
from .config import pipeline_fingerprint, pipeline_options
from .profiles import GRANITE_PROFILE, GRANITE_MODEL, PADDLE_MODEL, selected_profile


def overlap(a,b):
    area = max(0,a[2]-a[0]) * max(0,a[3]-a[1])
    intersection = max(0,min(a[2],b[2])-max(a[0],b[0])) * max(0,min(a[3],b[3])-max(a[1],b[1]))
    return intersection / area if area else 0


GRAPHIC_GROUP_REVIEW='来源图像范围与版面图表不一致；原图完整保留，需人工核对分组与图注。'


def incomplete_graphic_group(native_box, mapped):
    """A complete original crop cannot certify separate partial graphic roots."""
    full=[];partial=[]
    for block,loc in mapped:
        if block['kind'] not in {'figure','table'}:continue
        fraction=overlap(native_box,loc['bbox'])
        if fraction>=.9:full.append(block)
        elif .05<fraction<.9 and overlap(loc['bbox'],native_box)>=.8:partial.append(block)
    return {b['id']:b for b in full+partial} if full and partial else {}


def table_grid_complete(data):
    """Only emit a structured table when every grid slot has exactly one owner."""
    rows, columns = data.get('num_rows'), data.get('num_cols')
    if not isinstance(rows,int) or not isinstance(columns,int) or not 0<rows<=1000 or not 0<columns<=1000 or rows*columns>10000:
        return False
    occupied=set()
    try:
        for cell in data.get('table_cells',[]):
            if not isinstance(cell.get('text'),str):return False
            r0,r1,c0,c1=[cell[key] for key in ('start_row_offset_idx','end_row_offset_idx','start_col_offset_idx','end_col_offset_idx')]
            if not all(isinstance(value,int) for value in (r0,r1,c0,c1)) or not 0<=r0<r1<=rows or not 0<=c0<c1<=columns:return False
            if cell.get('row_span',r1-r0)!=r1-r0 or cell.get('col_span',c1-c0)!=c1-c0:return False
            slots={(row,column) for row in range(r0,r1) for column in range(c0,c1)}
            if occupied & slots:return False
            occupied.update(slots)
    except (KeyError,TypeError):
        return False
    return len(occupied)==rows*columns


def coverage_text(value):
    """Mechanical extraction equivalences only; never used to rewrite source text."""
    substitutions={'\ufb00':'ff','\ufb01':'fi','\ufb02':'fl','\ufb03':'ffi','\ufb04':'ffl',
                   '\u2018':"'",'\u2019':"'",'\u201c':'"','\u201d':'"','\u0002':'','\u00ad':''}
    for original,replacement in substitutions.items():value=value.replace(original,replacement)
    return ''.join(c for c in value if not c.isspace())


def coverage_characters(value):
    return Counter(coverage_text(value))


def vlm_text_issues(pages, blocks):
    """Native coverage catches omissions; also reject unsupported VLM additions."""
    issues = []
    for block in blocks:
        if block['kind'] in {'math', 'code'}:
            recognition = block['attributes'].get('recognition', {})
            original = recognition.get('original_text', '')
            if not original.strip():
                continue  # Scans already lack independent native evidence.
            native = unicodedata.normalize('NFKC', original)
            generated = unicodedata.normalize('NFKC', block['raw_text'])
            if block['kind'] == 'code':
                differs = ''.join(c for c in native if c.isalnum()) != ''.join(c for c in generated if c.isalnum())
                reason = 'Recognized code letters or digits differ from the native PDF; review the original crop'
            else:
                # This detects a concrete contradiction, not mathematical
                # equivalence. Preserve the image for all other formula checks.
                numbers = lambda s: Counter(re.findall(r'\d+(?:[.,]\d+)*', s.replace('{,}', ',')))
                differs = numbers(native) != numbers(generated)
                reason = 'Recognized formula numbers differ from the native PDF; review the original crop'
            if differs:
                loc = block['provenance'][0]
                issues.append({'page': loc['page'], 'bbox': loc['bbox'], 'block_ids': [block['id']],
                    'code': 'SOURCE_PARSE_REVIEW', 'reason': reason, 'text': original})
            continue
        if block['kind'] == 'table' and block['attributes'].get('representation') == 'structured':
            native = []
            for loc in block['provenance']:
                page = pages[loc['page'] - 1]
                native.extend(r['text'] for r in page['text_regions'] if overlap(r['bbox'], loc['bbox']) >= .6)
            if native or any(pages[loc['page'] - 1]['text_characters'] for loc in block['provenance']):
                cells = [b['raw_text'] for b in blocks if b.get('owner_id') == block['id'] and b['kind'] == 'table_cell']
                # Native regions may be rows or columns. Compare their complete
                # character inventory and numeric tokens without assuming cell
                # coordinates from HTML. Region coverage still checks omissions.
                numbers = lambda values: Counter(n for value in values for n in re.findall(r'\d+(?:[.,]\d+)*', value))
                if coverage_characters(''.join(native)) != coverage_characters(''.join(cells)) or numbers(native) != numbers(cells):
                    loc = block['provenance'][0]
                    issues.append({'page': loc['page'], 'bbox': loc['bbox'], 'block_ids': [block['id']],
                        'code': 'SOURCE_PARSE_REVIEW', 'reason': 'Recognized table cells differ from the native PDF; review the original table',
                        'text': '\n'.join(native)})
            continue
        if block['kind'] in {'figure', 'table', 'table_cell'}:
            continue
        native = []
        has_native_page = False
        for loc in block['provenance']:
            page = pages[loc['page'] - 1]
            has_native_page |= bool(page['text_characters'])
            native.extend(region['text'] for region in page['text_regions'] if overlap(region['bbox'], loc['bbox']) >= .6)
        text = coverage_text(block['raw_text'])
        if has_native_page and text and text not in coverage_text(''.join(native)):
            loc = block['provenance'][0]
            issues.append({'page': loc['page'], 'bbox': loc['bbox'], 'block_ids': [block['id']],
                'code': 'SOURCE_PARSE_REVIEW', 'reason': 'Native text does not support all VLM-generated text',
                'text': block['raw_text']})
    return issues


def native_paragraph_order_conflicts(page, blocks):
    """Report provable same-column inversions without guessing global layout.

    A two-column page, an owned caption, or a paragraph continuing through
    several regions needs explicit structural review, not a y-coordinate sort.
    The original order is retained so a reviewer can correct it with an audit.
    """
    candidates=[]
    for block in blocks:
        locs=block['provenance']
        if block['kind']!='paragraph' or block.get('owner_id') or len(locs)!=1 or locs[0]['page']!=page['page']:
            continue
        box=locs[0]['bbox'];text=coverage_text(block['raw_text'])
        proof=next((region for region in page['text_regions']
            if overlap(region['bbox'],box)>=.6 and coverage_text(region['text'])
            and coverage_text(region['text']) in text),None)
        if proof:candidates.append((block,box,proof))
    conflicts=[]
    for index,(first,a,first_native) in enumerate(candidates):
        for second,b,second_native in candidates[index+1:]:
            shared=min(a[2],b[2])-max(a[0],b[0])
            # Require separated vertical extents and strong overlap of BOTH
            # horizontal spans; narrow sidebars and adjacent columns are not
            # evidence of a shared text column. One point tolerates rounding.
            if b[3]+1>=a[1] or shared<.8*max(a[2]-a[0],b[2]-b[0]):continue
            conflicts.append({'page':page['page'],'bbox':b,'code':'SOURCE_PARSE_REVIEW',
                'reason':'Native same-column paragraph order conflicts with reading order',
                'block_ids':[first['id'],second['id']],
                'native_regions':[{'block_id':block['id'],'bbox':native['bbox'],'text':native['text']}
                    for block,native in [(first,first_native),(second,second_native)]],
                'disposition':'Original text and order retained; review the original page and explicitly correct the reading order'})
    return conflicts


def coverage_report(pages, blocks, excluded):
    report = {'pages':[],'unresolved':[],'excluded':excluded,'can_translate':True,'rule_version':'native-regions-v4-column-order',
              'comparison_equivalences':['ligature expansion','curly/straight quotation marks','PDFium U+0002 extraction marker and soft hyphen removal','whitespace']}
    for page in pages:
        number = page['page']
        mapped = [(block,loc) for block in blocks for loc in block['provenance'] if loc['page'] == number]
        unresolved, covered = [], []
        if page['scan_suspected']:
            unresolved.append({'page':number,
                'code':'SOURCE_PARSE_REVIEW' if page.get('ocr_attempted') else 'OCR_REQUIRED',
                'reason':'OCR was run; scan completeness cannot be independently verified against native text. Review the original page.'
                    if page.get('ocr_attempted') else 'Page has an image body without a reliable text layer'})
        for region in page['text_regions']:
            candidates = [b for b,loc in mapped if overlap(region['bbox'],loc['bbox']) >= .6]
            tables={b['id'] for b in candidates if b['kind']=='table' and b['attributes'].get('representation')=='structured'}
            # A native row spans several cells; combine only owned cells whose
            # actual locators intersect that row, never all text in a large table.
            candidates.extend(b for b,loc in mapped if b.get('owner_id') in tables and b not in candidates
                and min(loc['bbox'][2],region['bbox'][2])>max(loc['bbox'][0],region['bbox'][0])
                and max(0,min(loc['bbox'][3],region['bbox'][3])-max(loc['bbox'][1],region['bbox'][1]))
                    >=.6*min(loc['bbox'][3]-loc['bbox'][1],region['bbox'][3]-region['bbox'][1]))
            decorations = [e for e in excluded if e['page']==number and e.get('bbox') and overlap(region['bbox'],e['bbox']) >= .6]
            # Coordinates alone cannot excuse text dropped inside a broad table/paragraph box.
            native = coverage_text(region['text'])
            if not native:
                covered.append({'bbox':region['bbox'],'block_ids':[],'disposition':'native_decoder_marker'})
                continue
            # Preserve sequence as well as every meaningful character. A 97%
            # bag-of-characters threshold silently accepted dropped "not"/64.
            mapped_text = coverage_text(''.join(b['attributes'].get('recognition',{}).get('original_text',b['raw_text']) for b in candidates))
            represented = native in mapped_text
            # Text inside a declared original figure is explicitly retained, not
            # claimed translated. A whole-page figure cannot excuse missing body.
            image_fallback = any((b['kind'] in {'table','math','code'} and b['attributes'].get('representation')=='image' or b['kind']=='figure')
                and b['warnings'] and all((loc['bbox'][2]-loc['bbox'][0])*(loc['bbox'][3]-loc['bbox'][1]) < .65*loc['page_size'][0]*loc['page_size'][1] for loc in b['provenance']) for b in candidates)
            if decorations or (candidates and (represented or image_fallback)):
                covered.append({'bbox':region['bbox'],'block_ids':[b['id'] for b in candidates],'disposition':'excluded_decoration' if decorations else 'source'})
            else:
                unresolved.append({'page':number,'bbox':region['bbox'],'code':'SOURCE_PARSE_REVIEW','reason':'Native text region not fully represented','text':region['text']})
        for native_region in page.get('image_regions',[]) + page.get('graphic_regions',[]):
            candidates=[b for b,loc in mapped if b['kind'] in {'figure','table'} and overlap(native_region['bbox'],loc['bbox']) >= .9]
            ambiguous=incomplete_graphic_group(native_region['bbox'],mapped)
            if ambiguous:
                unresolved.append({'page':number,'bbox':native_region['bbox'],'code':'SOURCE_PARSE_REVIEW',
                    'reason':'Original image overlaps separate incomplete layout graphics','block_ids':list(ambiguous),
                    'disposition':'Original image retained; grouping and caption ownership require explicit source review'})
            if candidates:
                covered.append({'bbox':native_region['bbox'],'block_ids':[b['id'] for b in candidates],'disposition':'source_graphic'})
            else:
                unresolved.append({'page':number,'bbox':native_region['bbox'],'code':'SOURCE_PARSE_REVIEW','reason':'Native graphic region is not represented by a source figure/table'})
        if not mapped and page['text_characters']:
            unresolved.append({'page':number,'code':'SOURCE_PARSE_REVIEW','reason':'No parsed blocks for a text-bearing page'})
        unresolved.extend(native_paragraph_order_conflicts(page, blocks))
        report['pages'].append({k:page[k] for k in ['page','page_size','text_characters','scan_suspected']} | {'covered':covered,'unresolved':unresolved})
        report['unresolved'].extend(unresolved)
    report['can_translate'] = not report['unresolved'] and bool(blocks)
    return report


def _source_nodes(text, block_id, atoms, kind):
    if not text:return []
    if kind in {'code','math'}:
        atom_id = block_id + '-atom'
        atoms[atom_id] = {'kind':kind,'value':text}
        return [{'type':'protected_ref','ref':atom_id}] if text else []
    nodes, end = [], 0
    # CJK words legitimately touch numeric quantities ("包含64个"). ASCII
    # identifier boundaries protect those values while keeping abc64x intact.
    from .inline import tokens
    for index,match in enumerate(tokens(text)):
        if match.start() > end: nodes.append({'type':'text','text':text[end:match.start()]})
        if match.group().startswith(('https://','http://')):
            url=match.group().rstrip('.,;')
            from urllib.parse import urlsplit
            try:
                valid_url = len(url)<=2048 and bool(urlsplit(url).hostname)
            except ValueError:
                valid_url = False  # Malformed/example URLs remain literal source text.
            if valid_url:
                nodes.append({'type':'link','href':url,'text':url});end=match.start()+len(url);continue
            nodes.append({'type':'text','text':match.group()});end=match.end();continue
        atom_id = f'{block_id}-n{index}'
        atom_kind = 'citation' if match.lastgroup == 'citation' else 'number' if match.lastgroup == 'quantity' or match.lastgroup == 'scalar' and match.group()[0].isdigit() else 'math'
        atoms[atom_id] = {'kind':atom_kind,'value':match.group()}
        nodes.append({'type':'protected_ref','ref':atom_id}); end = match.end()
    if end < len(text): nodes.append({'type':'text','text':text[end:]})
    return nodes


class DoclingParser:
    def __init__(self, artifacts_path=None):
        self.artifacts_path = Path(artifacts_path or os.environ.get('DOCLING_ARTIFACTS_PATH','/opt/docling/models'))

    def parse(self, local_pdf, asset_id, output_dir, profile=None):
        profile = profile or {}
        if set(profile) - {'language','limits','created_at','parser_profile_revision'}:
            raise PDFError('PARSER_PROFILE_INVALID')
        try:
            selection = selected_profile(profile)
        except ValueError as exc:
            raise PDFError('PARSER_PROFILE_INVALID') from exc
        from .runtime import runtime_config, require_device
        require_device(runtime_config(selection), selection)
        lock = verify_models(self.artifacts_path)
        from .progress import local_identity, report_progress
        report_progress('loading_model', model=local_identity(selection, lock))
        inspection = inspect_pdf(local_pdf,profile.get('limits'))
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        from importlib.metadata import version
        if version('docling') != lock['docling_version']:
            raise PDFError('PARSER_VERSION_MISMATCH')
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        options = pipeline_options(self.artifacts_path, lock, selection)
        format_options = {'pipeline_options': options}
        if selection == GRANITE_PROFILE:
            from docling.pipeline.vlm_pipeline import VlmPipeline
            format_options['pipeline_cls'] = VlmPipeline
        converter = DocumentConverter(allowed_formats=[InputFormat.PDF],format_options={InputFormat.PDF:PdfFormatOption(**format_options)})
        try:
            converted = converter.convert(Path(local_pdf), raises_on_error=False, max_num_pages=inspection['page_count'])
        except Exception:
            # Inspection has already proved that the original PDF is readable.
            # A model/page failure can still yield native text and page images.
            converted = None
        if converted is not None and getattr(converted, 'document', None) is not None:
            report_progress('model_loaded', model=local_identity(selection, lock))
        else:
            report_progress('check_failed', phase='model_conversion')
        if converted is None or str(converted.status.value) != 'success':
            inspection.setdefault('warnings', []).append({'code': 'PARSER_PARTIAL_RESULT'})
        for page in inspection['pages']:page['ocr_attempted']=converted is not None
        output = Path(output_dir); output.mkdir(parents=True,exist_ok=True)
        document = getattr(converted, 'document', None)
        raw = document.export_to_dict() if document is not None else {}
        (output/'docling.json').write_bytes(canonical_bytes(raw))
        items = [item.model_dump(mode='json',by_alias=True) for item,_ in document.iterate_items()] if document is not None else []
        seen={item.get('self_ref') for item in items}
        # Default Docling iteration omits furniture. Its original labels and
        # coordinates are still needed to justify exclusions in the coverage ledger.
        items.extend(item for item in raw.get('texts',[]) if item.get('label') in {'page_header','page_footer'} and item.get('self_ref') not in seen)
        model_id = GRANITE_MODEL if selection == GRANITE_PROFILE else 'docling-project/CodeFormulaV2'
        model=next(repo for repo in lock['repositories'] if repo['repo_id']==model_id)
        def local_reparse(number):
            report_progress('loading_model', page=number, model=local_identity(selection, lock), phase='page_recovery')
            retried = converter.convert(Path(local_pdf), raises_on_error=False, page_range=(number, number), max_num_pages=inspection['page_count'])
            return [item.model_dump(mode='json', by_alias=True) for item, _ in retried.document.iterate_items()]
        local_reparse.model_identity = local_identity(selection, lock)
        result = self.adapt(items,inspection,local_pdf,asset_id,output,profile=profile,parser_version=lock['docling_version'],
            enrichment={'model':model['repo_id'],'revision':model['revision']},pipeline_hash=pipeline_fingerprint(lock, selection),
            recovery_callback=local_reparse)
        result['parser_profile_revision'] = selection
        return result

    def adapt(self, items, inspection, local_pdf, asset_id, output_dir, *, profile=None, parser_version=None, enrichment=None, pipeline_hash=None, parser_name='docling', recovery_callback=None):
        if parser_version is None:
            from .models import parser_version as locked_version
            parser_version = locked_version()
        """Convert a Docling item sequence; kept separate for contract and corpus testing."""
        import pypdfium2 as pdfium
        from .fidelity import reconcile_items
        from .recovery import recover_items
        from .progress import remaining_seconds
        profile = profile or {}; output = Path(output_dir); output.mkdir(parents=True,exist_ok=True)
        # Native reconciliation can repair code glyphs. Preserve the independent
        # VLM result before that pass, and only apply it to surviving code/formula leaves.
        recognized={item.get('self_ref'):dict(item) for item in items if enrichment and item.get('label') in {'code','formula'}}
        if enrichment and enrichment['model'] in {GRANITE_MODEL, PADDLE_MODEL}:
            # VLM orig is generated text too. Coverage of protected formula/code
            # uses independent native evidence within the retained PDF crop.
            from copy import deepcopy
            from .fidelity import box
            items = deepcopy(items)
            for item in items:
                if item.get('label') not in {'code', 'formula'}:
                    continue
                native = []
                for prov in item.get('prov', []):
                    page = inspection['pages'][prov['page_no'] - 1]
                    bounds = box(prov, inspection['pages'])
                    native.extend(region['text'] for region in page['text_regions'] if overlap(region['bbox'], bounds) >= .9)
                item['orig'] = '\n'.join(native)
        items,reconciliations=reconcile_items(items,inspection['pages'])
        items, recovery_audit = recover_items(items, inspection['pages'], local_reparse=recovery_callback, remaining_seconds=remaining_seconds)
        inspection['automatic_recovery'] = inspection.get('automatic_recovery', []) + recovery_audit
        inspection['reconciliations']=reconciliations
        source_file = output/'original.pdf'
        if Path(local_pdf).resolve() != source_file.resolve(): shutil.copyfile(local_pdf,source_file)
        assets = [{'id':asset_id,'media_type':'application/pdf','sha256':inspection['sha256'],'storage_key':'original.pdf','byte_size':inspection['byte_size']}]
        config_hash=digest({'profile':profile,'pipeline_hash':pipeline_hash}) if pipeline_hash else digest(profile)
        source = {'id':'src-'+inspection['sha256'][:20]+'-'+config_hash[:8], 'kind':'pdf_upload',
            'language':profile.get('language','und'),'original_asset_id':asset_id,'sha256':inspection['sha256'],
            'created_at':profile.get('created_at',datetime.now(timezone.utc).isoformat()),
            'parser':{'name':parser_name,'version':parser_version,'config_hash':config_hash},
            'normalization_version':'identity-v1','title_block_id':'','reading_order':[], 'assets':assets,'protected_atoms':{},'blocks':[]}
        blocks, atoms, excluded, issues = source['blocks'],source['protected_atoms'],[],[]
        item_blocks, caption_owners = {}, {}
        pdf = pdfium.PdfDocument(local_pdf)
        page_images = {}
        try:
            for info in inspection['pages']:
                if info['page_size'][0]*info['page_size'][1]*2.25 > 40_000_000:
                    raise PDFError('PDF_RESOURCE_LIMIT','Page render pixel limit exceeded')
                page = pdf[info['page']-1]
                try:
                    bitmap = page.render(scale=1.5)
                    image = bitmap.to_pil().copy(); bitmap.close()
                    file = output/f'pages/page-{info["page"]:04d}.png'; file.parent.mkdir(exist_ok=True)
                    image.save(file,format='PNG'); page_images[info['page']] = image
                    info['page_image'] = file.relative_to(output).as_posix()
                finally: page.close()
            def locator(prov):
                number = int(prov['page_no'])
                if not 1 <= number <= inspection['page_count']: raise PDFError('SOURCE_PARSE_REVIEW','Invalid Docling page number')
                w,h = inspection['pages'][number-1]['page_size']; bbox = prov['bbox']
                l,t,r,b = [float(bbox[k]) for k in ('l','t','r','b')]
                if str(bbox.get('coord_origin','TOPLEFT')).upper().endswith('BOTTOMLEFT'): t,b = h-t,h-b
                x0,y0,x1,y1 = max(0,min(l,r)),max(0,min(t,b)),min(w,max(l,r)),min(h,max(t,b))
                return {'type':'pdf','asset_id':asset_id,'page':number,'bbox':[x0,y0,x1,y1],'coordinate_system':'top-left-points','page_size':[w,h]}
            def make(kind,text,locs,attrs=None,owner=None):
                bid = 'b'+str(len(blocks))
                block = {'id':bid,'kind':kind,'order':len(blocks),'parent_id':source['title_block_id'] or None,
                    'owner_id':owner,'language':source['language'],'translatable':kind in {'heading','paragraph','list_item','caption','table_cell','footnote'},
                    'raw_text':text,'normalized_text':text,'normalization_edits':[], 'source_inline':_source_nodes(text,bid,atoms,kind),
                    'provenance':locs,'warnings':[],'attributes':attrs or {}}
                blocks.append(block)
                if owner is None:source['reading_order'].append(bid)
                return block
            def crop(locs,bid):
                loc = locs[0]; scale = 3
                left, top, right, bottom = loc['bbox']
                width, height = loc['page_size']
                if (right-left)*(bottom-top)*scale*scale > 40_000_000:
                    scale = 1.5
                page = pdf[loc['page']-1]
                try:
                    bitmap = page.render(scale=scale, crop=(left,height-bottom,width-right,top))
                    image = bitmap.to_pil().copy(); bitmap.close()
                finally:
                    page.close()
                if image.width*image.height <= 0: raise PDFError('SOURCE_PARSE_REVIEW','Empty figure crop')
                file = output/f'assets/{bid}.png'; file.parent.mkdir(exist_ok=True); image.save(file,format='PNG')
                image.close()
                aid = 'asset-'+bid
                assets.append({'id':aid,'media_type':'image/png','sha256':digest(file.read_bytes()),'byte_size':file.stat().st_size,'storage_key':file.relative_to(output).as_posix()})
                if len(assets)>501 or sum(a['byte_size'] for a in assets[1:])>200*1024*1024: raise PDFError('PDF_ASSET_LIMIT')
                return aid
            for item in items:
                label = item.get('label','text'); locs = [locator(p) for p in item.get('prov',[])]
                if not locs: continue  # Containers carry no content; leaf omissions remain in independent coverage.
                text = item.get('orig',item.get('text','')) or ''
                if label in {'page_header','page_footer'}:
                    for loc in locs:
                        # Only true page margins can be excluded by a layout label.
                        if (loc['bbox'][3] <= .12*loc['page_size'][1] or loc['bbox'][1] >= .88*loc['page_size'][1]
                            or loc['bbox'][2] <= .08*loc['page_size'][0] or loc['bbox'][0] >= .92*loc['page_size'][0]):
                            excluded.append({'page':loc['page'],'bbox':loc['bbox'],'reason':label,'text':text})
                        else:issues.append({'page':loc['page'],'code':'SOURCE_PARSE_REVIEW','reason':'Non-margin text labelled decoration','text':text})
                    continue
                kind = {'title':'heading','section_header':'heading','list_item':'list_item','code':'code','formula':'math','picture':'figure','table':'table','caption':'caption','footnote':'footnote','reference':'reference'}.get(label,'paragraph')
                if kind == 'heading': attrs = {'level':1 if not source['title_block_id'] else min(6,max(2,int(item.get('level',2))))}
                elif kind == 'list_item':
                    attrs = {'list_ordered':bool(item.get('enumerated',False))}
                    if isinstance(item.get('list_index'), int) and item['list_index'] >= 0:
                        attrs['list_index'] = item['list_index']
                elif kind in {'math','code'}: attrs = {'representation':'image'} if len(locs)==1 else {}
                elif kind in {'figure','table'}:attrs = {'caption_block_ids':[]}
                else:attrs = {}
                recognized_item=recognized.get(item.get('self_ref'),{}) if kind in {'math','code'} else {}
                recognized_text=recognized_item.get('text','') or ''
                if recognized_text.strip():
                    attrs['recognition']=enrichment | {'original_text':text}
                    text=recognized_text
                    attrs['representation']='latex' if kind=='math' else 'plain'
                    if kind=='code' and recognized_item.get('code_language'):attrs['code_language']=recognized_item['code_language']
                if kind == 'math' and item.get('_equation_number'):
                    attrs['equation_number'] = item['_equation_number']
                if not text and kind not in {'figure','table','math','code'} and not item.get('_nb_navigation_title'):continue
                block = make(kind,text,locs,attrs)
                if item.get('_nb_navigation_title'):
                    block['warnings'].append('未识别论文标题；导航使用首段原文，纯图像来源保留空标题。')
                if item.get('_nb_page_fallback'):
                    block['warnings'].append(f'第 {locs[0]["page"]} 页保留原 PDF 图像；图内内容未翻译。')
                if item.get('self_ref'): item_blocks[item['self_ref']] = block
                for caption_ref in item.get('captions',[]):
                    ref=caption_ref.get('$ref') if isinstance(caption_ref,dict) else None
                    if ref:caption_owners[ref]=block
                if kind == 'heading' and not source['title_block_id']:
                    source['title_block_id'] = block['id']; block['parent_id'] = None
                if kind in {'math','code'}:
                    if 'recognition' in attrs:
                        block['warnings'].append('公式/代码由本地解析模型识别；保留原PDF裁图供核对，识别结果可能有误。')
                    if len(locs)==1:
                        attrs['asset_id']=crop(locs,block['id'])
                        if 'recognition' not in attrs:block['warnings'].append('保留原PDF公式图像；文本抽取不代表公式的分数、上下标或排版。' if kind=='math' else '保留原PDF代码图像；文本抽取不代表代码的换行、缩进或语法排版。')
                    else:
                        if kind=='math' and 'recognition' not in attrs:attrs['representation']='plain'
                        issues.append({'code':'SOURCE_PARSE_REVIEW','reason':'Multi-region code/math requires explicit source layout correction','block_id':block['id']})
                if kind in {'figure','table'}:
                    if kind == 'table':
                        data = item.get('data',{}); cells = data.get('table_cells',[])
                        structured = table_grid_complete(data)
                        if structured:
                            attrs.update(representation='structured',rows=data['num_rows'],columns=data['num_cols'],cells=[])
                            for cell in cells:
                                cell_locs = locs
                                if cell.get('bbox'):
                                    cell_locs = [locator({'page_no':locs[0]['page'],'bbox':cell['bbox']})]
                                child = make('table_cell',cell['text'],cell_locs,owner=block['id'])
                                if not cell['text'].strip():child['translatable']=False
                                attrs['cells'].append({'row':cell['start_row_offset_idx'],'column':cell['start_col_offset_idx'],
                                    'row_span':cell.get('row_span',cell['end_row_offset_idx']-cell['start_row_offset_idx']),
                                    'column_span':cell.get('col_span',cell['end_col_offset_idx']-cell['start_col_offset_idx']),'content_block_id':child['id']})
                            block['raw_text']=block['normalized_text']='';block['source_inline']=[]
                            attrs['asset_id']=crop(locs,block['id'])
                            block['warnings'].append('表格由本地模型识别；保留原PDF表格供对照，单元格来源定位使用整表区域。')
                        else:
                            attrs.update(representation='image',asset_id=crop(locs,block['id']))
                            block['warnings'].append('表格结构未可靠恢复，保留原PDF表格图像；图内文字未翻译。')
                    else:
                        attrs['asset_id'] = crop(locs,block['id'])
                        block['warnings'].append('保留原PDF图像；图内文字未翻译。')
            # A real embedded image missed by layout inference remains an image
            # from this PDF. Keep it with an explicit warning, never synthesize it.
            for info in inspection['pages']:
                for native in info.get('image_regions',[]):
                    represented=any(b['kind'] in {'figure','table'} and any(loc['page']==info['page'] and overlap(native['bbox'],loc['bbox'])>=.9 for loc in b['provenance']) for b in blocks)
                    if represented:continue
                    loc={'type':'pdf','asset_id':asset_id,'page':info['page'],'bbox':native['bbox'],'coordinate_system':'top-left-points','page_size':info['page_size']}
                    block=make('figure','',[loc],{'caption_block_ids':[]})
                    block['attributes']['asset_id']=crop([loc],block['id'])
                    block['warnings'].append('版面模型未识别此原PDF图像；保留原图，请在预检核对位置。图内文字未翻译。')
                    source['reading_order'].remove(block['id'])
                    position=len(source['reading_order'])
                    for index,bid in enumerate(source['reading_order']):
                        candidate=next(b for b in blocks if b['id']==bid)
                        first=candidate['provenance'][0]
                        if first['page']>loc['page'] or first['page']==loc['page'] and first['bbox'][1]>loc['bbox'][1]:position=index;break
                    source['reading_order'].insert(position,block['id'])
            # Keep both original assets when the model identifies only part of
            # an embedded image. Display the ambiguity and block confirmation;
            # a complete fallback must not silently bless a partial caption owner.
            for info in inspection['pages']:
                mapped=[(b,loc) for b in blocks for loc in b['provenance'] if loc['page']==info['page']]
                for native in info.get('image_regions',[])+info.get('graphic_regions',[]):
                    for block in incomplete_graphic_group(native['bbox'],mapped).values():
                        if GRAPHIC_GROUP_REVIEW not in block['warnings']:block['warnings'].append(GRAPHIC_GROUP_REVIEW)
            for ref,owner in caption_owners.items():
                caption=item_blocks.get(ref)
                if caption and caption['kind']=='caption' and owner['kind'] in {'figure','table'}:
                    caption['owner_id']=owner['id'];source['reading_order'].remove(caption['id'])
                    owner['attributes']['caption_block_ids'].append(caption['id'])
                else:issues.append({'code':'SOURCE_PARSE_REVIEW','reason':'Unresolved caption ownership','reference':ref})
            if not source['title_block_id']:
                issues.append({'code':'SOURCE_PARSE_REVIEW','reason':'No reliable title was identified; source correction required'})
            ordered=[]
            def append_container(bid):
                ordered.append(bid)
                for child in blocks:
                    if child['owner_id']==bid:append_container(child['id'])
            for bid in source['reading_order']:append_container(bid)
            for block in blocks:block['order']=ordered.index(block['id'])
            blocks.sort(key=lambda block:block['order'])
            headings=[];bibliography=False
            for block in blocks:
                if block['kind']=='heading':
                    level=block['attributes']['level']
                    while headings and headings[-1]['attributes']['level']>=level:headings.pop()
                    block['parent_id']=headings[-1]['id'] if headings else None
                    headings.append(block)
                    bibliography=block['normalized_text'].strip().casefold() in {'references','bibliography','参考文献'}
                else:
                    block['parent_id']=headings[-1]['id'] if headings else source['title_block_id'] or None
                    if bibliography and block['kind']=='paragraph':block['kind']='reference';block['translatable']=False
            from .footnotes import link_native_footnotes
            inspection['footnote_links'] = link_native_footnotes(source, inspection)
            for block in blocks:
                if block['provenance'] and (block['kind'] in {'math', 'code', 'table', 'table_cell'} or any(
                        n['type'] == 'protected_ref' and atoms[n['ref']]['kind'] == 'number' for n in block['source_inline'])):
                    first = block['provenance'][0]
                    image_id = block['attributes'].get('asset_id')
                    scope = 'region' if image_id else 'page'
                    if image_id is None:
                        image_id = f'page-image-{first["page"]}'
                        if not any(a['id'] == image_id for a in assets):
                            file = output / f'pages/page-{first["page"]:04d}.png'
                            assets.append({'id': image_id, 'media_type': 'image/png', 'sha256': digest(file.read_bytes()),
                                'byte_size': file.stat().st_size, 'storage_key': file.relative_to(output).as_posix()})
                    block['attributes']['comparison_asset_id'] = image_id
                    block['attributes']['comparison_scope'] = scope
                block['source_hash'] = block_hash(block,atoms)
            check_started = datetime.now(timezone.utc).isoformat()
            check_failed = False
            try:
                coverage = coverage_report(inspection['pages'],blocks,excluded)
                if enrichment and enrichment['model'] in {GRANITE_MODEL, PADDLE_MODEL}:
                    issues.extend(vlm_text_issues(inspection['pages'], blocks))
            except (ValueError, RuntimeError, KeyError, TypeError):
                check_failed = True
                coverage = {'pages': [{'page': p['page']} for p in inspection['pages']], 'unresolved': []}
                issues.append({'code': 'CHECK_FAILED', 'reason': '检查未完成，原文与已提取内容仍可使用。'})
            inspection['quality_check'] = {'started_at': check_started,
                'finished_at': datetime.now(timezone.utc).isoformat(), 'state': 'failed' if check_failed else 'completed'}
            coverage['check_state'] = inspection['quality_check']['state']
            coverage['unresolved'].extend(issues)
            coverage['can_translate'] = not coverage['unresolved'] and bool(blocks)
            if source['title_block_id']:
                try:validate_source(source,asset_root=output)
                except ValueError as exc:
                    coverage['unresolved'].append({'code':'SOURCE_PARSE_REVIEW','reason':str(exc)});coverage['can_translate']=False
            else:source = None
            return {'source_revision':source,'coverage':coverage,'inspection':inspection,'parser_version':parser_version}
        finally:
            for image in page_images.values(): image.close()
            pdf.close()
