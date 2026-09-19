"""Strict syntax, source semantics and publication invariants for the stored render input."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import jsonschema
from .retention import original_only_blocks

from packages.paths import ROOT
SCHEMA = json.loads((ROOT / 'res/schemas/document-ir.schema.json').read_text('utf-8'))
RASTER_TYPES = {'image/png', 'image/jpeg', 'image/webp'}
PROSE = {'heading', 'paragraph', 'list_item', 'caption', 'table_cell', 'footnote'}


class IRValidationError(ValueError):
    def __init__(self, message, path='$', code='IR_INVALID'):
        self.path, self.code = path, code
        super().__init__(f'{path}: {message}')


def require(condition, message, path='$'):
    if not condition:
        raise IRValidationError(message, path)


def canonical_bytes(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError) as exc:
        raise IRValidationError('not canonical JSON') from exc


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical_bytes(value)).hexdigest()


def strict_loads(value):
    def pairs(items):
        result = {}
        for key, item in items:
            require(key not in result, f'duplicate key {key}')
            result[key] = item
        return result
    def bad_constant(_):
        raise IRValidationError('non-finite JSON number')
    try:
        return json.loads(value, object_pairs_hook=pairs, parse_constant=bad_constant)
    except (ValueError, UnicodeError) as exc:
        raise IRValidationError(str(exc)) from exc


def schema_validate(value, definition=None):
    canonical_bytes(value)  # jsonschema does not reject every nonfinite number itself.
    schema = SCHEMA if definition is None else {'$ref': f'#/$defs/{definition}', '$defs': SCHEMA['$defs']}
    errors = sorted(jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).iter_errors(value), key=lambda e: str(list(e.path)))
    if errors:
        error = errors[0]
        raise IRValidationError(error.message, '$.' + '.'.join(map(str, error.absolute_path)))


def safe_path(root, key, *, must_exist=True):
    require(isinstance(key, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', key), 'unsafe relative path')
    parts = PurePosixPath(key).parts
    require(all(p not in {'.', '..'} for p in parts) and '//' not in key, 'unsafe relative path')
    root = Path(root).resolve()
    target = root.joinpath(*parts)
    current = root
    for part in parts:
        current /= part
        require(not current.is_symlink(), 'symlink forbidden')
    require(target.resolve().is_relative_to(root), 'path escapes root')
    if must_exist:
        require(target.is_file(), 'asset missing')
    return target


def flatten_inline(nodes, atoms):
    result = []
    for node in nodes:
        if node['type'] == 'protected_ref':
            require(node['ref'] in atoms, 'unknown protected atom')
            result.append(atoms[node['ref']]['value'])
        elif node['type'] in {'text', 'link'}:
            result.append(node['text'])
        elif node['type'] == 'xref':
            result.append(node['label'])
        else:
            raise IRValidationError('unknown inline node')
    return ''.join(result)


def block_hash(block, atoms):
    refs = {n['ref']: atoms[n['ref']] for n in block['source_inline'] if n['type'] == 'protected_ref'}
    return digest({'kind': block['kind'], 'normalized_text': block['normalized_text'],
                   'source_inline': block['source_inline'], 'semantic_attributes': block['attributes'],
                   'resolved_protected_atoms': refs})


def inline_refs(nodes, atoms, blocks, path):
    flatten_inline(nodes, atoms)
    for node in nodes:
        if node['type'] == 'xref':
            require(node['target_block_id'] in blocks, 'unknown cross-reference', path)
        if node['type'] == 'link':
            url = node['href']
            parsed = urlsplit(url)
            require(not any(ord(c) < 32 for c in url) and '\\' not in url, 'unsafe URL', path)
            require(parsed.scheme in {'http', 'https', 'mailto'}, 'unsafe URL scheme', path)
            require(bool(parsed.netloc) if parsed.scheme != 'mailto' else bool(parsed.path), 'empty URL', path)
            require(parsed.username is None and parsed.password is None, 'URL credentials forbidden', path)


def empty_table_cell(block):
    return (block['kind'] == 'table_cell' and not block['raw_text'].strip() and not block['normalized_text'].strip()
        and all(n['type'] == 'text' and not n['text'].strip() for n in block['source_inline']))


def validate_source(source, document=None, asset_root=None, *, allow_missing_images=False):
    schema_validate(source, 'source_revision')
    blocks, assets, atoms = source['blocks'], source['assets'], source['protected_atoms']
    require(len(blocks) <= 10000 and sum(len(b['normalized_text']) for b in blocks) <= 1_000_000, 'source capacity exceeded')
    require(len(assets) <= 501, 'asset count exceeded')
    by, ab = {b['id']: b for b in blocks}, {a['id']: a for a in assets}
    require(len(by) == len(blocks), 'duplicate block IDs')
    require(len(ab) == len(assets), 'duplicate asset IDs')
    require(len({b['order'] for b in blocks}) == len(blocks), 'duplicate block order')
    original = ab.get(source['original_asset_id'])
    require(original and original['media_type'] == 'application/pdf' and original['sha256'] == source['sha256'], 'invalid original PDF binding')
    require(sum(a['byte_size'] for a in assets if a is not original) <= 200 * 1024 * 1024, 'asset bytes exceeded')
    for asset in assets:
        safe_path(asset_root or ROOT, asset['storage_key'], must_exist=False)
        require(asset['media_type'] in RASTER_TYPES | {'application/pdf'}, 'unsupported asset media type')
        require(asset is original or asset['media_type'] in RASTER_TYPES, 'only the original PDF may be a PDF asset')
        if asset_root is not None:
            if allow_missing_images and asset is not original and not safe_path(asset_root, asset['storage_key'], must_exist=False).exists():
                continue  # The reader must show an explicit original-PDF fallback.
            file = safe_path(asset_root, asset['storage_key'])
            require(file.stat().st_size == asset['byte_size'], 'asset size mismatch', asset['id'])
            require(digest(file.read_bytes()) == asset['sha256'], 'asset hash mismatch', asset['id'])
            if asset['media_type'] in RASTER_TYPES:
                from PIL import Image
                try:
                    with Image.open(file) as im:
                        require(im.width * im.height <= 40_000_000, 'image pixel limit exceeded')
                        expected_type = {'PNG':'image/png', 'JPEG':'image/jpeg', 'WEBP':'image/webp'}.get(im.format)
                        require(expected_type == asset['media_type'], 'raster format mismatch')
                        im.verify()
                except IRValidationError:
                    raise
                except Exception as exc:
                    raise IRValidationError('invalid raster image') from exc
    roots = {b['id'] for b in blocks if b['owner_id'] is None}
    require(set(source['reading_order']) == roots and len(source['reading_order']) == len(roots), 'root reading order mismatch')
    require(source['reading_order'] == sorted(roots, key=lambda i: by[i]['order']), 'reading order disagrees with block order')
    title = by.get(source['title_block_id'])
    require(title and title['id'] in roots and title['kind'] == 'heading', 'invalid title block')
    if document is not None:
        require(document['title'] == title['normalized_text'], 'source title drift')
    for block in blocks:
        path, kind, attributes = '$.blocks.' + block['id'], block['kind'], block['attributes']
        if block['parent_id'] is not None:
            require(block['parent_id'] in by and by[block['parent_id']]['kind'] == 'heading', 'parent must be a heading', path)
        seen, current = set(), block
        while current['parent_id'] is not None:
            require(current['id'] not in seen, 'parent cycle', path)
            seen.add(current['id'])
            require(current['parent_id'] in by, 'parent missing', path)
            current = by[current['parent_id']]
        owner = by.get(block['owner_id'])
        if block['owner_id'] is not None:
            require(owner and owner['owner_id'] is None, 'invalid owner', path)
            require((kind == 'caption' and owner['kind'] in {'figure','table'}) or (kind == 'table_cell' and owner['kind'] == 'table'), 'illegal owner kind', path)
        require(kind != 'table_cell' or owner, 'table cell cannot be a root', path)
        require(kind not in PROSE or block['translatable'] or empty_table_cell(block), 'prose cannot disable translation', path)
        text, previous = block['raw_text'], 0
        for edit in block['normalization_edits']:
            require(previous <= edit['raw_start'] <= edit['raw_end'] <= len(text), 'invalid code point edit interval', path)
            require(edit['rule_id'].strip() and edit['evidence'].strip(), 'normalization lacks evidence', path)
            previous = edit['raw_end']
        for edit in reversed(block['normalization_edits']):
            text = text[:edit['raw_start']] + edit['replacement'] + text[edit['raw_end']:]
        require(text == block['normalized_text'], 'normalization cannot be reproduced', path)
        inline_refs(block['source_inline'], atoms, by, path)
        require(flatten_inline(block['source_inline'], atoms) == text, 'inline source differs from normalized text', path)
        require(block_hash(block, atoms) == block['source_hash'], 'source hash mismatch', path)
        for loc in block['provenance']:
            require(loc['asset_id'] == source['original_asset_id'], 'locator must bind original PDF', path)
            x0,y0,x1,y1 = loc['bbox']; width,height = loc['page_size']
            require(all(math.isfinite(x) for x in loc['bbox'] + loc['page_size']), 'nonfinite locator', path)
            require(0 <= x0 <= x1 <= width and 0 <= y0 <= y1 <= height, 'bbox outside page', path)
        if 'asset_id' in attributes:
            require(attributes['asset_id'] in ab and ab[attributes['asset_id']]['media_type'] in RASTER_TYPES, 'missing raster asset', path)
        if 'comparison_asset_id' in attributes:
            require(attributes['comparison_asset_id'] in ab and ab[attributes['comparison_asset_id']]['media_type'] in RASTER_TYPES,
                    'missing comparison raster', path)
            require(bool(block['provenance']), 'comparison image has no source locator', path)
        if 'recognition' in attributes:
            require(kind in {'code','math'} and attributes.get('representation') in {'plain','latex'}
                    and bool(text.strip()) and bool(block['warnings']), 'invalid parser recognition evidence', path)
        captions = attributes.get('caption_block_ids', [])
        require(len(captions) == len(set(captions)), 'duplicate caption reference', path)
        for cid in captions:
            require(cid in by and by[cid]['kind'] == 'caption' and by[cid]['owner_id'] == block['id'], 'caption ownership mismatch', path)
        if kind == 'caption' and owner:
            require(block['id'] in owner['attributes'].get('caption_block_ids', []), 'orphan caption', path)
        if kind == 'table_cell':
            require(block['id'] in [c['content_block_id'] for c in owner['attributes'].get('cells', [])], 'orphan cell', path)
        if kind == 'table' and attributes['representation'] == 'structured':
            require(attributes['rows'] * attributes['columns'] <= 100000, 'table grid too large', path)
            cells, covered = set(), set()
            for cell in attributes['cells']:
                cid = cell['content_block_id']
                require(cid in by and by[cid]['kind'] == 'table_cell' and by[cid]['owner_id'] == block['id'] and cid not in cells, 'invalid table cell reference', path)
                cells.add(cid)
                require(cell['row'] + cell['row_span'] <= attributes['rows'] and cell['column'] + cell['column_span'] <= attributes['columns'], 'cell out of bounds', path)
                for row in range(cell['row'], cell['row'] + cell['row_span']):
                    for col in range(cell['column'], cell['column'] + cell['column_span']):
                        require((row,col) not in covered, 'overlapping table cells', path)
                        covered.add((row,col))
            require(len(covered) == attributes['rows'] * attributes['columns'], 'table coverage gap', path)
        if kind == 'math':
            require(attributes['representation'] in {'plain','latex','image'}, 'unsupported math representation', path)
            require('asset_id' in attributes if attributes['representation'] == 'image' else bool(text.strip()), 'math has no reliable representation', path)
        if kind == 'table' and attributes['representation'] == 'image':
            require(bool(block['warnings']), 'image table needs visible fallback warning', path)
    return source


def validate_ir(value, asset_root=None):
    schema_validate(value)
    source, translation = value['source_revision'], value['translation_revision']
    validate_source(source, value['document'], asset_root,
        allow_missing_images=value['translation_revision'].get('content_policy') == 'nonblocking-v1')
    require(translation['source_revision_id'] == source['id'], 'translation bound to another source')
    by = {b['id']: b for b in source['blocks']}
    results = {r['block_id']: r for r in translation['results']}
    require(len(results) == len(translation['results']) and set(results) == set(by), 'translation results are not bijective')
    atoms = source['protected_atoms']
    nonblocking = translation.get('content_policy') == 'nonblocking-v1'
    original_only = original_only_blocks(source)
    for rid, result in results.items():
        block, path = by[rid], '$.results.' + rid
        require(result['source_hash'] == block['source_hash'], 'stale target source hash', path)
        inline_refs(result['target_inline'], atoms, by, path)
        if result['status'] == 'fallback':
            require(nonblocking and not result['target_inline'] and bool(result['reason'].strip()), 'invalid content fallback', path)
            require('fallback' in result and result['review_state'] == 'not_reviewed', 'fallback must not claim translation or review', path)
            if result['fallback']['mode'] == 'source_page':
                require(bool(block['provenance']), 'page fallback has no source locator', path)
        elif result['status'] == 'unresolved':
            require(value['render']['mode'] == 'draft', 'unresolved block in release', path)
        elif result['status'] == 'translated':
            require(bool(flatten_inline(result['target_inline'], atoms).strip()), 'empty translation', path)
            for node_type, field in [('protected_ref','ref'),('xref','target_block_id'),('link','href')]:
                a = Counter(n[field] for n in block['source_inline'] if n['type'] == node_type)
                b = Counter(n[field] for n in result['target_inline'] if n['type'] == node_type)
                if nonblocking:
                    require(set(b) <= set(a), 'target invents a source link or reference', path)
                    continue
                if node_type == 'protected_ref':
                    from .quantities import protected_counts
                    a, b = protected_counts(block['source_inline'], result['target_inline'], atoms, translation['target_language'])
                require(a == b, f'{node_type} multiplicity mismatch', path)
        else:
            require(not result['target_inline'] and bool(result['reason'].strip()), 'invalid retained result', path)
            require(block['kind'] in {'code','math','figure','reference','table'} or empty_table_cell(block)
                or result['reason'] == original_only.get(rid)
                or (result['reason'] == 'same_language' and block['language'] == translation['target_language']),
                'required prose cannot be retained', path)
        review = result['review_record']
        if result['review_state'] == 'human_reviewed':
            require(review and review['origin'] == 'manual_ui', 'missing explicit manual review record', path)
            require(review['source_hash'] == block['source_hash'] and review['target_hash'] == digest(result['target_inline']) and review['context_hash'] == result['context_hash'] and review['glossary_revision'] == result['generation']['glossary_revision'], 'stale manual review', path)
        else:
            require(review is None, 'active review record contradicts review state', path)
    title_result = results[source['title_block_id']]
    title_text = by[source['title_block_id']]['normalized_text'] if title_result['status'] in {'retained', 'fallback'} else flatten_inline(title_result['target_inline'], atoms)
    require(translation['title'] == title_text, 'translation title drift')
    return value
