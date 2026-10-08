"""Separate numbered bibliography entries with their printed PDF boundaries."""
from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
import re
import unicodedata

from packages.ir.retention import REFERENCE_HEADINGS, _heading_label
from .recovery import _bounds, _native_lines, _overlap, _union
from .rich_ir import carry_reference_semantics


VERSION = 'native-reference-boundaries-v1'
MARKER = re.compile(r'^\s*\[(\d{1,4}[a-z]?)\]\s*')


def _core(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def _baselines(regions, width):
    # Small-cap author fonts can leave several separately grouped runs on one
    # line. Rejoin those runs before testing the printed hanging marker.
    groups = []
    for line in _native_lines(regions, width):
        box = line['bbox']
        aligned = [group for group in groups if any(
            min(box[3], other['bbox'][3]) - max(box[1], other['bbox'][1]) >=
            .5 * min(box[3] - box[1], other['bbox'][3] - other['bbox'][1])
            for other in group)]
        group = [line]
        for old in aligned:
            group.extend(old)
            groups.remove(old)
        groups.append(group)
    return sorted([{'text': ' '.join(line['text'] for line in sorted(group, key=lambda r: r['bbox'][0])),
                    'bbox': _union([line['bbox'] for line in group])} for group in groups], key=lambda r: r['bbox'][1])


def _split(item, page):
    """Preserve source words; only native hanging markers justify a new entry."""
    text = item.get('orig', item.get('text', ''))
    bounds = _bounds(item, page)
    if not text or not bounds or len(text) > 60000:
        return None
    regions = [r for r in page.get('text_regions', []) if _overlap(r['bbox'], bounds) >= .6]
    lines = _native_lines(regions, page['page_size'][0])
    if not lines:
        return None
    # A physical reference area must be one column. A native citation/year in
    # a title is not a hanging marker merely because a PDF font run starts there.
    middle = page['page_size'][0] / 2
    if any(r['bbox'][2] < middle for r in lines) and any(r['bbox'][0] > middle for r in lines):
        return None
    lines = _baselines(regions, page['page_size'][0])
    left = min(r['bbox'][0] for r in lines)
    anchors = [(index, MARKER.match(line['text'])) for index, line in enumerate(lines)
               if line['bbox'][0] <= left + 8]
    anchors = [(index, match) for index, match in anchors if match]
    if not anchors:
        return None
    starts = []
    for index, marker in anchors:
        label = marker[1]
        matches = list(re.finditer(r'(?<!\S)\[' + re.escape(label) + r'\]\s*', text))
        if len(matches) != 1:
            return None
        match = matches[0]
        # The same printed label and opening words must identify the entry.
        # Do not guess a sequence, correct OCR words, or split a cited [1990]
        # occurring within a reference's title.
        native = _core(lines[index]['text'][marker.end():])
        model = _core(text[match.end():])
        size = min(32, len(native), len(model))
        if size < 5 or SequenceMatcher(None, native[:size], model[:size], autojunk=False).ratio() < .85:
            return None
        starts.append((match.start(), index))
    if starts != sorted(starts) or len({start for start, _ in starts}) != len(starts):
        return None
    first_start, first_line = starts[0]
    if text[:first_start].strip():
        if not first_line or _core(text[:first_start]) != _core(' '.join(line['text'] for line in lines[:first_line])):
            return None
        starts.insert(0, (0, 0))
    elif first_line:
        # Unexpected native prose before the first model entry is not discarded.
        return None
    else:
        starts[0] = (0, first_line)
    if len(starts) < 2:
        return None
    fragments = []
    for ordinal, ((start, line_start), (end, line_end)) in enumerate(zip(starts, starts[1:] + [(len(text), len(lines))])):
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        proof = lines[line_start:line_end]
        if not proof or start == end:
            return None
        fragment = deepcopy(item)
        fragment.update(self_ref=item['self_ref'] + f'/native-reference-{ordinal}',
                        label='reference', orig=text[start:end], text=text[start:end])
        prov = deepcopy(item['prov'][0])
        prov.update(bbox=dict(zip(('l', 't', 'r', 'b'), _union([line['bbox'] for line in proof])), coord_origin='TOPLEFT'),
                    charspan=[0, end - start])
        fragment['prov'] = [prov]
        fragment['native_reference_regions'] = deepcopy(proof)
        carry_reference_semantics(item, fragment, start, end)
        tree = fragment.get('_semantic')
        while tree and tree['kind'] == 'group' and len(tree['children']) == 1 and tree['children'][0]['text'] == tree['text']:
            child = tree['children'][0]
            child['attrs'] = {**tree['attrs'], **child['attrs']}
            tree = fragment['_semantic'] = child
        fragments.append(fragment)
    return fragments


def recover_references(items, pages):
    """Split only bibliographic records, before paragraph continuation recovery."""
    pages = {page['page']: page for page in pages}
    output, audit = [], []
    bibliography = False
    for item in items:
        text = item.get('orig', item.get('text', ''))
        if item.get('label') in {'title', 'section_header'}:
            bibliography = _heading_label(text) in REFERENCE_HEADINGS
        fragments = None
        if (item.get('label') == 'reference' or bibliography and item.get('label') in {'text', 'paragraph'}) and len(item.get('prov', [])) == 1:
            page = pages.get(item['prov'][0]['page_no'])
            if page:
                fragments = _split(item, page)
        if not fragments:
            output.append(item)
            continue
        output.extend(fragments)
        at = datetime.now(timezone.utc).isoformat()
        audit.append(dict(origin='automatic_recovery', rule_version=VERSION,
            page=item['prov'][0]['page_no'], action='native_reference_boundaries',
            item_ref=item['self_ref'], before=text, after=[row['orig'] for row in fragments],
            native_evidence=[row['native_reference_regions'] for row in fragments],
            started_at=at, finished_at=at, elapsed_ms=0, model=None))
    return output, audit
