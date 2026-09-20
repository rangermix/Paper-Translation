"""Conservative footnote links for fresh parses, using native glyph evidence."""
from collections import defaultdict
import math
import re

from packages.ir import flatten_inline


LABEL = re.compile(r'^\s*([0-9]{1,3})(?:[.)]?\s+)')
PROSE = {'paragraph', 'heading', 'list_item', 'caption', 'table_cell'}


def _overlap(first, second):
    area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    intersection = max(0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0, min(first[3], second[3]) - max(first[1], second[1]))
    return intersection / area if area else 0


def native_footnote_markers(glyphs):
    """Retain bounded, raised-small numeric runs and their neighboring prose.

    This is optional evidence, not a text rewrite or a footnote decision. The
    adapter must still prove a unique same-page note and an exact source/native
    occurrence. Require sentence-ending punctuation after a prose word; a
    directly word-attached superscript can be an exponent and must abstain.
    """
    result = []
    position = 0
    while position < len(glyphs):
        first = glyphs[position]
        if not re.fullmatch('[0-9]', first['text']):
            position += 1
            continue
        start = position
        position += 1
        while position < len(glyphs) and re.fullmatch('[0-9]', glyphs[position]['text']):
            position += 1
        marker = glyphs[start:position]
        if len(marker) > 3 or start == 0:
            continue
        # PDFium can insert CR/LF at font-size boundaries. The geometric check
        # below still requires the marker to touch the preceding punctuation.
        cursor = start - 1
        while cursor >= 0 and glyphs[cursor]['text'].isspace():
            cursor -= 1
        body_end = cursor + 1
        if cursor < 0 or glyphs[cursor]['text'] not in '.?':
            continue
        cursor -= 1
        word_end = cursor + 1
        while cursor >= max(0, body_end - 33) and re.fullmatch('[A-Za-z]', glyphs[cursor]['text']):
            cursor -= 1
        word = ''.join(g['text'] for g in glyphs[cursor + 1:word_end])
        if not 3 <= len(word) <= 32:
            continue
        context = glyphs[cursor + 1:body_end]
        body = context[-1]
        size = body.get('font_size', 0)
        if not math.isfinite(size) or size <= 0 or 'origin' not in body:
            continue
        baseline = body['origin'][1]
        if any('origin' not in g or abs(g['origin'][1] - baseline) > .1 * size
               or not .9 * size <= g.get('font_size', 0) <= 1.1 * size for g in context):
            continue
        if any('origin' not in g or not .45 * size <= g.get('font_size', 0) <= .8 * size
               or not .18 * size <= g['origin'][1] - baseline <= .8 * size for g in marker):
            continue
        if any(abs(g['origin'][1] - first['origin'][1]) > .1 * size
               or not -.1 * size <= g['bbox'][0] - previous['bbox'][2] <= .35 * size
               for previous, g in zip([body] + marker, marker)):
            continue
        bounds = [min(g['bbox'][0] for g in marker), min(g['bbox'][1] for g in marker),
                  max(g['bbox'][2] for g in marker), max(g['bbox'][3] for g in marker)]
        if bounds[3] > body['bbox'][3] - .15 * size:
            continue
        following = position
        while following < len(glyphs) and glyphs[following]['text'].isspace():
            following += 1
        if following < len(glyphs):
            neighbor = glyphs[following]
            if (neighbor.get('origin') and abs(neighbor['origin'][1] - baseline) <= .1 * size
                    and 0 <= neighbor['bbox'][0] - bounds[2] <= size):
                if neighbor['text'] in '=+-*/^<>':
                    continue
                context = context + marker + [neighbor]
            else:
                context = context + marker
        else:
            context = context + marker
        result.append({'label': ''.join(g['text'] for g in marker), 'bbox': bounds,
            'native_indices': [g['index'] for g in marker],
            'context': {'text': ''.join(g['text'] for g in context),
                        'native_indices': [g['index'] for g in context]},
            'body_font_size': size, 'marker_font_size': first['font_size'],
            'rise': first['origin'][1] - baseline})
    return result


def _alignment(block, pages):
    """Map original glyph occurrences to source offsets, ignoring only spaces."""
    native = {}
    for loc in block['provenance']:
        page = pages.get(loc['page'], {})
        for region in page.get('text_regions', []):
            if _overlap(region['bbox'], loc['bbox']) < .6:
                continue
            indices = region.get('native_indices', [])
            if len(indices) != len(region['text']):
                return None
            for index, character in zip(indices, region['text']):
                key = (loc['page'], index)
                if key in native and native[key] != character:
                    return None
                native[key] = character
    keys = [key for key in sorted(native) if not native[key].isspace()]
    native_text = ''.join(native[key] for key in keys)
    offsets = [index for index, character in enumerate(block['normalized_text']) if not character.isspace()]
    source_text = ''.join(block['normalized_text'][index] for index in offsets)
    start = native_text.find(source_text) if source_text else -1
    if start < 0 or start != native_text.rfind(source_text):
        return None
    return dict(zip(keys[start:start + len(source_text)], offsets))


def _replace_marker(nodes, start, end, label, target, atoms):
    """Split text or replace a whole number atom; preserve all other structure."""
    cursor = 0
    left, right = [], []
    for node in nodes:
        value = flatten_inline([node], atoms)
        stop = cursor + len(value)
        if cursor < end and stop > start:
            if node['type'] == 'text' and 'code' not in node.get('marks', []):
                pass
            elif not (node['type'] == 'protected_ref' and atoms[node['ref']]['kind'] == 'number'
                      and cursor == start and stop == end):
                return None
            if cursor < start:
                left.append({**node, 'text': value[:start - cursor]})
            if stop > end:
                right.append({**node, 'text': value[end - cursor:]})
        elif stop <= start:
            left.append(node)
        else:
            right.append(node)
        cursor = stop
    return left + [{'type': 'xref', 'label': label, 'target_block_id': target}] + right


def link_native_footnotes(source, inspection):
    """Annotate newly built source inlines before its first source hashes exist."""
    if (inspection.get('sha256') != source.get('sha256')
            or any('source_hash' in block for block in source['blocks'])):
        return []
    pages = {page['page']: page for page in inspection['pages']}
    labels = defaultdict(list)
    for block in source['blocks']:
        if block['kind'] != 'footnote':
            continue
        match = LABEL.match(block['normalized_text'])
        numbers = {loc['page'] for loc in block['provenance']}
        if match and len(numbers) == 1:
            labels[next(iter(numbers)), match[1]].append(block)
    if not labels:
        return []
    alignments = {}
    def alignment(block):
        if block['id'] not in alignments:
            alignments[block['id']] = _alignment(block, pages)
        return alignments[block['id']]
    audit = []
    for page in pages.values():
        for marker in page.get('footnote_markers', []):
            targets = labels.get((page['page'], marker['label']), [])
            if len(targets) != 1 or not alignment(targets[0]):
                continue
            context = marker['context']
            marker_indices = marker['native_indices']
            if (len(marker_indices) != len(marker['label']) or not marker_indices
                    or len(context['native_indices']) != len(context['text'])):
                continue
            offsets = [offset for offset in range(len(context['native_indices']))
                if context['native_indices'][offset:offset + len(marker_indices)] == marker_indices
                and context['text'][offset:offset + len(marker_indices)] == marker['label']]
            if len(offsets) != 1:
                continue
            matches = []
            for block in source['blocks']:
                if block['kind'] not in PROSE or not any(loc['page'] == page['page']
                        and _overlap(marker['bbox'], loc['bbox']) >= .9 for loc in block['provenance']):
                    continue
                mapping = alignment(block)
                if (not mapping
                        or any((page['page'], index) not in mapping
                            or block['normalized_text'][mapping[page['page'], index]] != character
                            for index, character in zip(context['native_indices'], context['text']))):
                    continue
                indices = [mapping.get((page['page'], index)) for index in marker['native_indices']]
                if not indices or any(index is None for index in indices):
                    continue
                start, end = indices[0], indices[-1] + 1
                text = block['normalized_text']
                if (text[start:end] != marker['label'] or (end < len(text)
                        and not (text[end].isspace() or text[end] in '.,;:!?)，。'))):
                    continue
                matches.append((block, start, end))
            if len(matches) != 1:
                continue
            block, start, end = matches[0]
            nodes = _replace_marker(block['source_inline'], start, end, marker['label'],
                                    targets[0]['id'], source['protected_atoms'])
            if nodes is None:
                continue
            block['source_inline'] = nodes
            audit.append({'action': 'native_numeric_footnote_link', 'page': page['page'],
                'block_id': block['id'], 'target_block_id': targets[0]['id'], 'label': marker['label'],
                'source_start': start, 'source_end': end, 'native_indices': marker['native_indices'],
                'bbox': marker['bbox']})
    return audit
