"""Mechanical corrections never use model text or rewrite the original PDF.

The stored parser region, quote and locator are checked together. Lexical changes
are refused unless a future parser-evidence protocol can independently prove them.
"""
from __future__ import annotations

import copy
import re

from packages.domain.errors import require
from packages.ir import block_hash, digest, flatten_inline, validate_source


def _mechanical(text):
    for before, after in {'\ufb00': 'ff', '\ufb01': 'fi', '\ufb02': 'fl', '\ufb03': 'ffi', '\ufb04': 'ffl', '\u00ad': ''}.items():
        text = text.replace(before, after)
    text = re.sub(r'(?<=\w)-\s*\n\s*(?=\w)', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def _mapping_index(source):
    """Content identities omit serialization IDs and physical PDF positions.

    Inline structure, resolved atoms, links, referenced semantic blocks and media
    hashes still participate. Unverifiable/cyclic references cannot become reuse
    evidence. This index proposes correspondence; it never copies translations or
    review records to the new source revision.
    """
    blocks = {block['id']: block for block in source['blocks']}
    assets = {asset['id']: asset for asset in source.get('assets', [])}
    atoms = source.get('protected_atoms', {})
    identities, valid = {}, {}

    def content(bid, visiting=()):
        if bid in visiting or len(visiting) >= 64:
            raise ValueError('Unverifiable semantic reference cycle')
        if bid in identities:
            return identities[bid]
        block = blocks[bid]
        path = (*visiting, bid)

        def resolve(value, key=''):
            if key == 'asset_id':
                asset = assets[value]
                return {'media_type': asset['media_type'], 'sha256': asset['sha256']}
            if key.endswith('_block_id'):
                identity = content(value, path)
                if not valid[value]:
                    raise ValueError('Unverifiable referenced block')
                return identity
            if key.endswith('_block_ids'):
                return [resolve(item, 'referenced_block_id') for item in value]
            if isinstance(value, list):
                return [resolve(item) for item in value]
            if isinstance(value, dict):
                if value.get('type') == 'protected_ref':
                    return {'type': 'protected_ref', 'resolved': resolve(atoms[value['ref']])}
                return {name: resolve(item, name) for name, item in value.items()}
            return value

        try:
            valid[bid] = block_hash(block, atoms) == block['source_hash']
            payload = {name: resolve(block[name]) for name in
                ('kind', 'language', 'translatable', 'normalized_text', 'source_inline', 'attributes')}
            # A corrupt stored fingerprint cannot be laundered into an exact
            # semantic match simply because its visible text looks unchanged.
            if not valid[bid]:
                payload['unverified_source_hash'] = block['source_hash']
            identities[bid] = digest(payload)
        except (KeyError, ValueError, TypeError):
            valid[bid] = False
            identities[bid] = digest({'unverifiable_block': bid})
        return identities[bid]

    for bid in blocks:
        content(bid)
    contexts = {}
    ordered = [block['id'] for block in source['blocks']]
    for position, bid in enumerate(ordered):
        ancestors, seen = [], {bid}
        parent = blocks[bid].get('parent_id')
        while parent:
            if parent in seen or parent not in blocks:
                valid[bid] = False
                break
            seen.add(parent)
            ancestors.append(content(parent))
            if not valid[parent]:
                valid[bid] = False
            parent = blocks[parent].get('parent_id')
        owner = blocks[bid].get('owner_id')
        if owner is not None and (owner not in blocks or not valid[owner]):
            valid[bid] = False
        contexts[bid] = digest({'ancestors': ancestors,
            'owner': content(owner) if owner in blocks else None,
            'before': [content(item) for item in ordered[max(0, position-1):position]],
            'after': [content(item) for item in ordered[position+1:position+2]]})
    return blocks, identities, contexts, valid


def revision_mapping(before, after, structural=None):
    """Match unique semantic evidence, never coincidental block ordinals."""
    old, old_content, old_context, old_valid = _mapping_index(before)
    new, new_content, new_context, new_valid = _mapping_index(after)
    mapped = []
    touched_old, touched_new = set(), set()
    for item in structural or []:
        mapped.append({**item, 'reusable': False, 'context_changed': True})
        touched_old.update(item['old_block_ids'])
        touched_new.update(item['new_block_ids'])
    pairs = {}

    def pair(old_id, new_id):
        pairs[old_id] = new_id
        touched_old.add(old_id)
        touched_new.add(new_id)

    def unique_matches(old_key, new_key):
        old_groups, new_groups = {}, {}
        for bid in old:
            if bid not in touched_old:
                old_groups.setdefault(old_key(bid), []).append(bid)
        for bid in new:
            if bid not in touched_new:
                new_groups.setdefault(new_key(bid), []).append(bid)
        for key, old_ids in old_groups.items():
            new_ids = new_groups.get(key, [])
            if len(old_ids) == len(new_ids) == 1:
                pair(old_ids[0], new_ids[0])

    # Unique content remains identifiable when an insertion changes its immediate
    # context. Repeated content needs a unique semantic context on both sides.
    unique_matches(lambda bid: old_content[bid], lambda bid: new_content[bid])
    unique_matches(lambda bid: (old_content[bid], old_context[bid]),
        lambda bid: (new_content[bid], new_context[bid]))

    same_original = before.get('sha256') == after.get('sha256') and before.get('original_asset_id') == after.get('original_asset_id')
    if same_original:
        for bid in old:
            if bid not in touched_old and bid in new and bid not in touched_new:
                # Mechanical editing of one frozen PDF retains stronger evidence
                # than an ordinal: its exact original page regions must agree.
                if old[bid].get('provenance') == new[bid].get('provenance'):
                    pair(bid, bid)

    for old_id in old:
        if old_id in pairs:
            new_id = pairs[old_id]
            identical = old_content[old_id] == new_content[new_id]
            context_changed = old_context[old_id] != new_context[new_id]
            kind = 'changed' if not identical else ('moved' if old[old_id]['order'] != new[new_id]['order'] else 'exact')
            mapped.append({'kind': kind, 'old_block_ids': [old_id], 'new_block_ids': [new_id],
                'reusable': identical and not context_changed and old_valid[old_id] and new_valid[new_id],
                'context_changed': context_changed})
        elif old_id not in touched_old:
            mapped.append({'kind': 'unmatched', 'old_block_ids': [old_id], 'new_block_ids': [], 'reusable': False, 'context_changed': True})
    for bid in new:
        if bid in touched_new:
            continue
        mapped.append({'kind': 'unmatched', 'old_block_ids': [], 'new_block_ids': [bid], 'reusable': False, 'context_changed': True})
    return mapped


def _evidence_blocks(source, evidence):
    require(isinstance(evidence, dict) and set(evidence) == {'page', 'bbox', 'quote'}, 'SOURCE_EVIDENCE_REQUIRED', status=422)
    quote, bbox, page = evidence['quote'], evidence['bbox'], evidence['page']
    require(isinstance(quote, str) and quote.strip() and isinstance(page, int) and page >= 1 and isinstance(bbox, list) and len(bbox) == 4, 'SOURCE_EVIDENCE_REQUIRED', status=422)
    verified = set()
    for block in source['blocks']:
        quote_match = quote in block['raw_text'] or quote in block['normalized_text']
        locator_match = any(loc['page'] == page and loc['bbox'] == bbox and loc['asset_id'] == source['original_asset_id'] for loc in block['provenance'])
        if quote_match and locator_match:
            verified.add(block['id'])
    require(bool(verified), 'SOURCE_EVIDENCE_MISMATCH', 'The quote and region must match the stored original-PDF parser evidence.', status=422)
    return verified


def _normalization(block, normalized, evidence, reason):
    block['normalized_text'] = normalized
    block['normalization_edits'] = [] if normalized == block['raw_text'] else [{
        'raw_start': 0, 'raw_end': len(block['raw_text']), 'replacement': normalized,
        'rule_id': 'manual-pdf-mechanical-v1', 'reviewed': False,
        'evidence': f'{reason}; page={evidence["page"]}; bbox={evidence["bbox"]}; quote={evidence["quote"]}',
    }]


def _split_inline(nodes, offset, atoms):
    left, right, cursor = [], [], 0
    for node in nodes:
        text = flatten_inline([node], atoms)
        end = cursor + len(text)
        if end <= offset:
            left.append(copy.deepcopy(node))
        elif cursor >= offset:
            right.append(copy.deepcopy(node))
        else:
            require(node['type'] == 'text', 'PROTECTED_ATOM_SPLIT', 'Cannot split a protected atom, link or cross-reference.', status=422)
            at = offset - cursor
            left.append({**node, 'text': text[:at]})
            right.append({**node, 'text': text[at:]})
        cursor = end
    return left, right


def _set_order(source, root_order):
    by = {b['id']: b for b in source['blocks']}
    order = []
    for root in root_order:
        order.append(by[root])
        order.extend(b for b in source['blocks'] if b['owner_id'] == root)
    require(len(order) == len(source['blocks']), 'SOURCE_ORDER_INVALID', status=422)
    for index, block in enumerate(order):
        block['order'] = index
    source['blocks'] = order
    source['reading_order'] = root_order


def apply_corrections(source, operations, evidence, reason):
    validate_source(source)
    require(isinstance(reason, str) and reason.strip(), 'SOURCE_REASON_REQUIRED', status=422)
    require(isinstance(operations, list) and 0 < len(operations) <= 100, 'SOURCE_OPERATIONS_INVALID', status=422)
    evidenced = _evidence_blocks(source, evidence)
    result = copy.deepcopy(source)
    structural = []
    for op_index, op in enumerate(operations):
        require(isinstance(op, dict), 'SOURCE_OPERATION_INVALID', status=422)
        kind = op.get('kind')
        by = {b['id']: b for b in result['blocks']}
        if kind == 'reorder':
            require(set(op) == {'kind', 'block_ids'}, 'SOURCE_OPERATION_INVALID', status=422)
            order = op['block_ids']
            require(isinstance(order, list) and len(order) == len(set(order)) and set(order) == set(result['reading_order']), 'SOURCE_ORDER_INVALID', status=422)
            _set_order(result, order)
        elif kind == 'replace_text':
            require(set(op) == {'kind', 'block_id', 'start', 'end', 'text'}, 'SOURCE_OPERATION_INVALID', status=422)
            block = by.get(op['block_id'])
            require(block is not None and block['id'] in evidenced, 'SOURCE_EVIDENCE_MISMATCH', status=422)
            start, end, replacement = op['start'], op['end'], op['text']
            require(type(start) is int and type(end) is int and 0 <= start <= end <= len(block['normalized_text']) and isinstance(replacement, str), 'SOURCE_OFFSET_INVALID', status=422)
            normalized = block['normalized_text'][:start] + replacement + block['normalized_text'][end:]
            require(_mechanical(normalized) == _mechanical(block['raw_text']), 'SOURCE_UNPROVEN_TEXT', 'Only mechanical whitespace, ligature and line-wrap restoration is proven by this evidence.', status=422)
            # Preserve semantic inline nodes; editing through protected content is forbidden.
            left, tail = _split_inline(block['source_inline'], start, result['protected_atoms'])
            middle, right = _split_inline(tail, end - start, result['protected_atoms'])
            require(all(n['type'] == 'text' for n in middle), 'SOURCE_PROTECTED_EDIT', 'A mechanical text edit cannot remove protected content.', status=422)
            block['source_inline'] = left + ([{'type': 'text', 'text': replacement}] if replacement else []) + right
            _normalization(block, normalized, evidence, reason)
        elif kind == 'split':
            require(set(op) == {'kind', 'block_id', 'offset'}, 'SOURCE_OPERATION_INVALID', status=422)
            block = by.get(op['block_id'])
            require(block is not None and block['id'] in evidenced and block['kind'] == 'paragraph' and block['owner_id'] is None, 'SOURCE_SPLIT_UNSUPPORTED', status=422)
            offset = op['offset']
            require(type(offset) is int and 0 < offset < len(block['normalized_text']), 'SOURCE_OFFSET_INVALID', status=422)
            require(block['raw_text'] == block['normalized_text'], 'SOURCE_SPLIT_MAPPING_REQUIRED', 'Split a mechanically normalized block only after an explicit raw-to-normalized mapping is available.', status=422)
            left, right = _split_inline(block['source_inline'], offset, result['protected_atoms'])
            other = copy.deepcopy(block)
            other['id'] = f'{block["id"]}_split_{op_index + 1}'
            require(other['id'] not in by, 'SOURCE_ID_CONFLICT', status=422)
            other['raw_text'] = block['raw_text'][offset:]
            block['raw_text'] = block['raw_text'][:offset]
            block['source_inline'], other['source_inline'] = left, right
            _normalization(block, block['raw_text'], evidence, reason)
            _normalization(other, other['raw_text'], evidence, reason)
            result['blocks'].append(other)
            root_order = list(result['reading_order'])
            root_order.insert(root_order.index(block['id']) + 1, other['id'])
            _set_order(result, root_order)
            structural.append({'kind': 'split', 'old_block_ids': [block['id']], 'new_block_ids': [block['id'], other['id']]})
        elif kind == 'merge':
            require(set(op) == {'kind', 'block_ids'}, 'SOURCE_OPERATION_INVALID', status=422)
            ids = op['block_ids']
            require(isinstance(ids, list) and 2 <= len(ids) <= 100 and len(set(ids)) == len(ids) and set(ids) <= by.keys(), 'SOURCE_MERGE_INVALID', status=422)
            blocks = [by[bid] for bid in ids]
            require(all(b['kind'] == 'paragraph' and b['owner_id'] is None for b in blocks) and len({b['parent_id'] for b in blocks}) == 1 and bool(set(ids) & evidenced), 'SOURCE_MERGE_UNSUPPORTED', status=422)
            at = result['reading_order'].index(ids[0])
            require(result['reading_order'][at:at + len(ids)] == ids, 'SOURCE_MERGE_NOT_ADJACENT', status=422)
            first = blocks[0]
            raw, nodes = '', []
            for b in blocks:
                separator = '' if not raw or raw[-1:].isspace() or b['raw_text'][:1].isspace() else ' '
                raw += separator + b['raw_text']
                if separator:
                    nodes.append({'type': 'text', 'text': separator})
                nodes.extend(copy.deepcopy(b['source_inline']))
            first['raw_text'], first['source_inline'] = raw, nodes
            _normalization(first, flatten_inline(nodes, result['protected_atoms']), evidence, reason)
            first['provenance'] = list({digest(loc): loc for b in blocks for loc in b['provenance']}.values())
            result['blocks'] = [b for b in result['blocks'] if b['id'] not in ids[1:]]
            for b in result['blocks']:
                for node in b['source_inline']:
                    if node.get('target_block_id') in ids[1:]:
                        node['target_block_id'] = first['id']
            _set_order(result, [bid for bid in result['reading_order'] if bid not in ids[1:]])
            structural.append({'kind': 'merged', 'old_block_ids': ids, 'new_block_ids': [first['id']]})
        else:
            require(False, 'SOURCE_OPERATION_UNSUPPORTED', status=422)
    for block in result['blocks']:
        block['source_hash'] = block_hash(block, result['protected_atoms'])
    validate_source(result)
    return {'source': result, 'mapping': revision_mapping(source, result, structural), 'evidence': copy.deepcopy(evidence), 'reason': reason}
