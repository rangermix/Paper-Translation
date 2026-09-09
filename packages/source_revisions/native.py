"""Restore only character evidence already captured by the isolated PDF inspector.

No PDF is decoded here. A lexical restoration must reproduce all native text
regions covered by that source block; a short quote cannot authorize deleting
the rest of a broad paragraph. Original parser drafts remain immutable.
"""
import copy
import re

from packages.domain.errors import require
from packages.ir import block_hash, digest, validate_source
from packages.parsers.pdf_docling import _source_nodes, coverage_report, overlap
from .corrections import _set_order, revision_mapping


def _space(text):
    return re.sub(r'\s+', ' ', text).strip()


def verified_native_region(inspection, evidence):
    require(isinstance(evidence, dict) and set(evidence) == {'page', 'bbox', 'quote'}, 'SOURCE_EVIDENCE_REQUIRED', status=422)
    for page in inspection.get('pages', []):
        if page['page'] != evidence['page']:
            continue
        for region in page['text_regions']:
            if region['bbox'] == evidence['bbox'] and region['text'] == evidence['quote'] and region['text'].strip():
                return page, region
    require(False, 'SOURCE_NATIVE_EVIDENCE_MISMATCH', 'Quote and coordinates must exactly match the persisted native PDF region.', status=422)


def native_regions_for_block(inspection, block):
    return [(page, region) for page in inspection.get('pages', []) for region in page['text_regions']
        if any(loc['page'] == page['page'] and overlap(region['bbox'], loc['bbox']) >= .6 for loc in block['provenance'])]


def _locator(source, page, region):
    return {'type': 'pdf', 'asset_id': source['original_asset_id'], 'page': page['page'],
        'bbox': region['bbox'], 'coordinate_system': 'top-left-points', 'page_size': page['page_size']}


def apply_native_corrections(source, inspection, operations, evidence, reason, excluded, *, crop_asset=None,page_image_verify=None):
    require(source and inspection and inspection.get('sha256') == source.get('sha256'), 'SOURCE_NATIVE_EVIDENCE_REQUIRED')
    validate_source(source)
    require(isinstance(reason, str) and reason.strip(), 'SOURCE_REASON_REQUIRED', status=422)
    require(isinstance(operations, list) and 0 < len(operations) <= 100, 'SOURCE_OPERATIONS_INVALID', status=422)
    page, region = verified_native_region(inspection, evidence)
    result = copy.deepcopy(source)
    restorations = [];structural=[]
    for op in operations:
        require(isinstance(op, dict), 'SOURCE_OPERATION_INVALID', status=422)
        kind = op.get('kind')
        if kind == 'annotate_footnote':
            from .relations import annotate_footnote
            restorations.append(annotate_footnote(result,op,evidence,reason,page_image_verify))
        elif kind == 'normalize_native_span':
            from .normalization import normalize_native_span
            restorations.append(normalize_native_span(result,inspection,op,evidence,reason,page_image_verify))
        elif kind == 'merge_continuation':
            from .relations import merge_continuation
            mapping,restoration=merge_continuation(result,op,evidence,reason,page_image_verify)
            structural.append(mapping);restorations.append(restoration)
        elif kind == 'merge_native_continuation':
            from .relations import merge_native_continuation
            mapping,restoration=merge_native_continuation(result,inspection,op,evidence,reason,page_image_verify)
            structural.append(mapping);restorations.append(restoration)
        elif kind == 'split_with_math_crop':
            from .math_crop import split_with_math_crop
            mapping,restoration=split_with_math_crop(result,op,evidence,reason,crop_asset)
            structural.append(mapping);restorations.append(restoration)
        elif kind == 'annotate_math_crop':
            from .math_crop import annotate_math_crop
            mapping,restoration=annotate_math_crop(result,op,evidence,reason,crop_asset,inspection)
            structural.append(mapping);restorations.append(restoration)
        elif kind == 'replace_text':
            require(set(op) == {'kind', 'block_id', 'start', 'end', 'text'}, 'SOURCE_OPERATION_INVALID', status=422)
            block = next((b for b in result['blocks'] if b['id'] == op['block_id']), None)
            require(block is not None, 'SOURCE_BLOCK_NOT_FOUND', status=422)
            regions = native_regions_for_block(inspection, block)
            require(any(p['page'] == page['page'] and r == region for p, r in regions), 'SOURCE_NATIVE_EVIDENCE_MISMATCH', status=422)
            start, end, replacement = op['start'], op['end'], op['text']
            require(type(start) is int and type(end) is int and isinstance(replacement, str) and 0 <= start <= end <= len(block['normalized_text']), 'SOURCE_OFFSET_INVALID', status=422)
            proposed = block['normalized_text'][:start] + replacement + block['normalized_text'][end:]
            native = '\n'.join(r['text'] for p, r in regions)
            require(_space(proposed) == _space(native), 'SOURCE_UNPROVEN_TEXT',
                'The complete corrected block must reproduce every native region covered by its original coordinates.', status=422)
            restorations.append({'block_id': block['id'], 'parser_raw_text': block['raw_text'], 'native_raw_text': native,
                'regions': [{'page': p['page'], **r} for p, r in regions]})
            block['raw_text'] = native
            if block['attributes'].pop('recognition', None) is not None:
                block['attributes']['representation'] = 'image' if block['attributes'].get('asset_id') else 'plain'
                block['warnings'] = ['来源文字已按原PDF文本层校正；原件裁图保留供核对。']
            block['normalized_text'] = proposed
            block['normalization_edits'] = [] if native == proposed else [{'raw_start': 0, 'raw_end': len(native), 'replacement': proposed,
                'rule_id': 'native-pdf-whitespace-v1', 'reviewed': False, 'evidence': reason}]
            block['source_inline'] = _source_nodes(proposed, block['id'], result['protected_atoms'], block['kind'])
            block['provenance'] = [_locator(result, p, r) for p, r in regions]
        elif kind == 'recover_region':
            require(set(op) == {'kind', 'page', 'bbox', 'quote', 'after_block_id'}, 'SOURCE_OPERATION_INVALID', status=422)
            proof = {k: op[k] for k in ('page', 'bbox', 'quote')}
            recovered_page, recovered_region = verified_native_region(inspection, proof)
            require(proof == evidence, 'SOURCE_NATIVE_EVIDENCE_MISMATCH', status=422)
            overlapping = [b for b in result['blocks'] if b['raw_text'].strip() and any(loc['page'] == op['page'] and overlap(op['bbox'], loc['bbox']) >= .6 for loc in b['provenance'])]
            require(not overlapping, 'SOURCE_REGION_PARTIALLY_MAPPED', 'Restore the existing block against all of its native regions instead of duplicating an already mapped region.', status=422)
            after = op['after_block_id']
            require(after in result['reading_order'], 'SOURCE_ORDER_INVALID', status=422)
            bid = 'recovered-' + digest(proof)[:24]
            require(all(b['id'] != bid for b in result['blocks']), 'SOURCE_REGION_ALREADY_RECOVERED')
            text = op['quote']
            result['blocks'].append({'id': bid, 'kind': 'paragraph', 'order': len(result['blocks']),
                'parent_id': result['title_block_id'], 'owner_id': None, 'language': result['language'], 'translatable': True,
                'raw_text': text, 'normalized_text': text, 'normalization_edits': [],
                'source_inline': _source_nodes(text, bid, result['protected_atoms'], 'paragraph'),
                'provenance': [_locator(result, recovered_page, recovered_region)], 'warnings': [], 'attributes': {}})
            order = list(result['reading_order'])
            order.insert(order.index(after) + 1, bid)
            _set_order(result, order)
            restorations.append({'block_id': bid, 'parser_raw_text': None, 'native_raw_text': text, 'regions': [proof]})
        elif kind == 'reorder':
            require(set(op) == {'kind', 'block_ids'} and isinstance(op['block_ids'], list) and len(op['block_ids']) == len(set(op['block_ids'])) and set(op['block_ids']) == set(result['reading_order']), 'SOURCE_ORDER_INVALID', status=422)
            _set_order(result, op['block_ids'])
        else:
            require(False, 'SOURCE_OPERATION_UNSUPPORTED', status=422)
        for block in result['blocks']:
            block['source_hash'] = block_hash(block, result['protected_atoms'])
        validate_source(result)
    return {'source': result, 'mapping': revision_mapping(source, result,structural), 'evidence': copy.deepcopy(evidence),
        'restorations': restorations, 'coverage': coverage_report(inspection['pages'], result['blocks'], excluded)}
