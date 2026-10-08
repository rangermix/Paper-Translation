"""Evidence-bound relationships across PDF page/column and graphic boundaries."""
from copy import deepcopy
from datetime import datetime, timezone
import re

from packages.quality.issues import comparison_text
from .recovery import _bounds, _complete_native_coverage, _matches, _native_lines, _overlap, _union

VERSION = 'native-layout-relations-v2'


def recover_duplicate_regions(items, page_list):
    """Discard only misplaced duplicates with independent native coverage proof.

    Identical wording can legitimately appear twice. A duplicate is removable
    only when one occurrence matches its native PDF text, the other does not,
    and ALL native content under the misplaced box already belongs elsewhere.
    """
    pages = {page['page']: page for page in page_list}
    groups = {}
    audit = []
    for item in items:
        value = item.get('orig', item.get('text', '')).strip()
        tree = item.get('_semantic')
        if (item.get('label') not in {'text', 'paragraph'} or len(item.get('prov', [])) != 1 or
                len(value) < 80 or tree and (tree['children'] or any(r['type'] in {'math', 'code', 'control'} for r in tree['runs']))):
            continue
        groups.setdefault((item['prov'][0]['page_no'], comparison_text(value)), []).append(item)
    for (number, _), group in groups.items():
        if len(group) < 2 or number not in pages:
            continue
        page = pages[number]
        candidates = []
        for item in group:
            bounds = _bounds(item, page)
            proof = [r for r in page.get('text_regions', []) if _overlap(r['bbox'], bounds) >= .6 and any(c.isalnum() for c in r['text'])]
            size = sum(sum(c.isalnum() for c in r['text']) for r in proof)
            supported = sum(sum(c.isalnum() for c in r['text']) for r in proof if _matches(r, item))
            candidates.append((item, proof, supported / size if size >= 40 else None))
        verified = [(item, proof) for item, proof, support in candidates if support is not None and support >= .85]
        if len(verified) != 1:
            continue
        retained, retained_proof = verified[0]
        for item, proof, support in candidates:
            if support is None or support > .1 or item is retained:
                continue
            def represented(region):
                return any(other is not item and other is not retained and
                           any(loc.get('page_no') == number for loc in other.get('prov', [])) and _bounds(other, page) and
                           _overlap(region['bbox'], _bounds(other, page)) >= .6 and
                           (other.get('label') in {'picture', 'table', 'formula', 'code'} or _matches(region, other))
                           for other in items)
            if not all(represented(region) for region in proof):
                continue
            items.remove(item)
            at = datetime.now(timezone.utc).isoformat()
            audit.append(dict(origin='automatic_recovery', rule_version=VERSION, page=number,
                action='native_misplaced_duplicate', before=item.get('orig', item.get('text', '')), after=[],
                item_ref=item.get('self_ref'), retained_ref=retained.get('self_ref'),
                native_evidence=proof, retained_native_evidence=retained_proof,
                started_at=at, finished_at=at, elapsed_ms=0, model=None))
    return items, audit


def recover_inline_layout(items, page_list):
    """Recover run-in headings and bullet boundaries from their native baselines."""
    from .rich_ir import merge_semantics, slice_semantics
    pages = {p['page']: p for p in page_list}
    audit = []
    def record(action, before, after, page, proof):
        at = datetime.now(timezone.utc).isoformat()
        audit.append(dict(origin='automatic_recovery', rule_version=VERSION, page=page,
            action=action, before=before, after=after, native_evidence=proof,
            started_at=at, finished_at=at, elapsed_ms=0, model=None))
    def text(row):
        return row.get('orig', row.get('text', '')).strip()
    def local(row):
        if len(row.get('prov', [])) != 1:
            return None
        page = pages.get(row['prov'][0]['page_no'])
        return page if page and row.get('label') in {'text', 'paragraph'} else None
    # A model can complete a short run-in heading's hyphenated final word and
    # put the following prose in another block. The native suffix and body on
    # the SAME baseline prove that this is one paragraph, not a section break.
    for first, second in list(zip(items, items[1:])):
        page = local(first)
        if not page or local(second) is not page or first not in items or second not in items:
            continue
        left, right = text(first), text(second)
        if not 8 <= len(left) <= 180 or not right:
            continue
        lb, rb = _bounds(first, page), _bounds(second, page)
        if abs(lb[0] - rb[0]) > 12 or not -3 <= rb[1] - lb[3] <= 15:
            continue
        left_lines = _native_lines([r for r in page['text_regions'] if _overlap(r['bbox'], lb) >= .6])
        right_regions = [r for r in page['text_regions'] if _overlap(r['bbox'], rb) >= .6]
        right_lines = _native_lines(right_regions)
        if not left_lines or not right_lines:
            continue
        stem = re.search(r'([A-Za-z]+)[\-\x02\u00ad]$', left_lines[-1]['text'].strip())
        suffix = re.match(r'([a-z]+)([.,;:]?)\s+(\S.*)', right_lines[0]['text'].strip())
        if not stem or not suffix or not left.endswith(stem[1] + suffix[1] + suffix[2]):
            continue
        if not right.startswith(suffix[3].rstrip('-\x02\u00ad')):
            continue
        # The heading's complete native prefix must match its emitted wording;
        # coincidental suffixes or missing heading text do not authorize a join.
        core = lambda s: ''.join(c for c in s if c.isalnum())
        native_left = core(' '.join(line['text'] for line in left_lines))
        if core(left) != native_left + suffix[1]:
            continue
        first_line = right_lines[0]['bbox']
        if first_line[1] - left_lines[-1]['bbox'][3] > max(1, first_line[3] - first_line[1]) * .8:
            continue
        merge_semantics(first, second)
        merged = left + ' ' + right
        first['orig'] = first['text'] = merged
        first['prov'][0]['bbox'] = dict(zip(('l', 't', 'r', 'b'), _union([lb, rb])), coord_origin='TOPLEFT')
        items.remove(second)
        record('native_run_in_paragraph', [left, right], [merged], page['page'], [*left_lines, right_lines[0]])

    # Bullet glyphs printed at distinct baselines establish list boundaries even
    # when the model has flattened them into a single paragraph. Exact model
    # slices retain its source text and marks; geometry comes from native lines.
    expanded = []
    for item in items:
        page = local(item); original = text(item); tree = item.get('_semantic')
        markers = list(re.finditer(r'(?:^|\s)([•▪◦])\s*', original))
        if not page or len(markers) < 2 or markers[0].start() != 0 or (tree and tree['children']):
            expanded.append(item); continue
        bounds = _bounds(item, page)
        regions = [r for r in page['text_regions'] if _overlap(r['bbox'], bounds) >= .6]
        glyphs = sorted((r for r in regions if r['text'].strip() in {'•', '▪', '◦'}), key=lambda r: r['bbox'][1])
        if len(glyphs) != len(markers) or any(abs(r['bbox'][0] - glyphs[0]['bbox'][0]) > 2 for r in glyphs):
            expanded.append(item); continue
        parts = []; valid = True
        for i, (marker, glyph) in enumerate(zip(markers, glyphs)):
            start = marker.end(); end = markers[i + 1].start() if i + 1 < len(markers) else len(original)
            while end > start and original[end - 1].isspace(): end -= 1
            part = original[start:end]
            bottom = glyphs[i + 1]['bbox'][1] if i + 1 < len(glyphs) else bounds[3] + 1
            proof = [r for r in regions if glyph['bbox'][1] - 5 <= r['bbox'][1] < bottom - 5 and r['text'].strip() not in {'•', '▪', '◦'}]
            native_lines = _native_lines(proof)
            opening = re.findall(r'\w+', part)[:3]
            if not native_lines or re.findall(r'\w+', native_lines[0]['text'])[:3] != opening:
                valid = False; break
            clone = deepcopy(item)
            clone.update(self_ref=item['self_ref'] + f'/native-list-{i}', label='list_item', orig=part, text=part, enumerated=False)
            clone['prov'][0]['bbox'] = dict(zip(('l', 't', 'r', 'b'), _union([glyph['bbox'], *[r['bbox'] for r in proof]])), coord_origin='TOPLEFT')
            if tree:
                semantic = slice_semantics(tree, start, end)
                if not semantic:
                    valid = False; break
                semantic['kind'] = 'list_item'; semantic['attrs']['list_ordered'] = False
                clone['_semantic'] = semantic
            parts.append(clone)
        if valid:
            expanded.extend(parts)
            record('native_bullet_list', [original], [text(r) for r in parts], page['page'], regions)
        else:
            expanded.append(item)
    return expanded, audit


def _line_edge(lines, *, last=False):
    """Choose the outer run on a baseline, independent of math/font ascent."""
    edge = lines[-1 if last else 0]
    box = edge['bbox']
    aligned = [line for line in lines if
        min(line['bbox'][3], box[3]) - max(line['bbox'][1], box[1]) >=
        min(line['bbox'][3] - line['bbox'][1], box[3] - box[1]) * .5]
    return (max(aligned, key=lambda line: line['bbox'][2]) if last else
            min(aligned, key=lambda line: line['bbox'][0]))


def _native_prefix_end(text, native_lines, bounds, suffix):
    """Bound a model-completed page tail with full original paragraph evidence."""
    # A whole native baseline must not fit into an unexplained top/bottom gap
    # or between the observed lines. Sparse text cannot justify deleting prose.
    if not _complete_native_coverage(native_lines, bounds):
        return None
    native = comparison_text(' '.join(line['text'] for line in native_lines))
    native_core = ''.join(c for c in native if c.isalnum())
    positions = [index for index, c in enumerate(text) if c.isalnum()]
    model_core = ''.join(text[index] for index in positions)
    if not native_core or not model_core.startswith(native_core) or len(native_core) >= len(positions):
        return None
    cut = positions[len(native_core) - 1] + 1
    tail = text[cut:]
    # The model must have completed the very word split in the original PDF.
    # This is not a general deletion/rewrite rule for disagreeing source text.
    if len(tail) <= 240 and re.match(re.escape(suffix) + r'(?=\W|$)', tail):
        return cut
    return None


def recover_layout(items, pages):
    pages = {p['page']: p for p in pages}
    audit = []

    def record(action, before, after, page, **evidence):
        at = datetime.now(timezone.utc).isoformat()
        audit.append(dict(origin='automatic_recovery', rule_version=VERSION, page=page,
            action=action, before=before, after=after, started_at=at, finished_at=at,
            elapsed_ms=0, model=None, **evidence))

    def text(row):
        return row.get('orig', row.get('text', '')).strip()

    def lines(row, page, bounds=None):
        bounds = bounds or _bounds(row, page)
        if not bounds:
            return []
        proof = []
        for region in page.get('text_regions', []):
            box = region['bbox']
            height = max(1, box[3] - box[1])
            aligned = min(box[2], bounds[2]) - max(box[0], bounds[0]) >= (box[2] - box[0]) * .6
            # Match the recovery pass's protection for rounded/clipped model
            # rectangles. A nearby exact line is still part of this paragraph.
            nearby = (aligned and bounds[1] <= box[1] <= bounds[3] + height * 1.5 and
                      _matches(region, row))
            if _overlap(box, bounds) >= .6 or nearby:
                proof.append(region)
        return _native_lines(proof)

    def ordered_region(row):
        if row.get('label') not in {'text', 'paragraph', 'section_header', 'title', 'list_item', 'reference'} or len(row.get('prov', [])) != 1:
            return None
        page = pages.get(row['prov'][0].get('page_no'))
        if not page:
            return None
        proof = lines(row, page)
        if not any(_matches(line, row) and len(re.findall(r'[A-Za-z]', line['text'])) >= 3 for line in proof):
            return None
        return page, _bounds(row, page), proof

    # Correct adjacent same-column inversions only. Column transitions and
    # full-width resources/captions remain fixed boundaries in reading order.
    visible = [index for index, row in enumerate(items) if text(row) or row.get('label') in {'picture', 'table', 'formula', 'code'}]
    changed = True
    while changed:
        changed = False
        for left_index, right_index in zip(visible, visible[1:]):
            first, second = items[left_index], items[right_index]
            left, right = ordered_region(first), ordered_region(second)
            if not left or not right or left[0]['page'] != right[0]['page']:
                continue
            page, lb, left_proof = left
            _, rb, right_proof = right
            width = page['page_size'][0]
            same_column = (lb[2] <= width * .55 and rb[2] <= width * .55 or
                           lb[0] >= width * .45 and rb[0] >= width * .45)
            if (same_column and rb[3] <= lb[1] and
                    max(line['bbox'][3] for line in right_proof) <= min(line['bbox'][1] for line in left_proof)):
                items[left_index], items[right_index] = second, first
                changed = True
                record('native_reading_order', [text(first), text(second)], [text(second), text(first)],
                       page['page'], native_evidence=[*right_proof, *left_proof])

    def list_candidate(row):
        if row.get('label') not in {'text', 'paragraph'} or len(row.get('prov', [])) != 1:
            return None
        marker = re.match(r'^(\d{1,3})([.)])\s+(\S+)', text(row))
        page = pages.get(row['prov'][0].get('page_no'))
        if not marker or not page:
            return None
        proof = lines(row, page)
        if not proof:
            return None
        first = _line_edge(proof)
        if not re.match(re.escape(marker[1] + marker[2]) + r'\s+' + re.escape(marker[3]) + r'(?:\s|$)', first['text']):
            return None
        height = first['bbox'][3] - first['bbox'][1]
        hanging = any(line['bbox'][1] >= first['bbox'][3] and
                      line['bbox'][0] - first['bbox'][0] > height * .65 for line in proof)
        return dict(row=row, index=int(marker[1]), marker=marker[2], page=page['page'],
                    box=_bounds(row, page), height=height, hanging=hanging, proof=proof)

    group = []
    def finish_list():
        if len(group) < 2 or not any(candidate['hanging'] for candidate in group):
            return
        before = [text(candidate['row']) for candidate in group]
        for candidate in group:
            candidate['row'].update(label='list_item', enumerated=True, list_index=candidate['index'])
        record('native_list_sequence', before, before, group[0]['page'],
               list_indices=[candidate['index'] for candidate in group],
               native_evidence=[line for candidate in group for line in candidate['proof']])

    # Adjacent, sequential native markers and hanging continuations establish a
    # list. Numbers in ordinary prose, section titles or other columns do not.
    for row in [*items, {}]:
        candidate = list_candidate(row)
        compatible = False
        if candidate and group:
            previous = group[-1]
            height = max(candidate['height'], previous['height'])
            compatible = (candidate['page'] == previous['page'] and
                candidate['index'] == previous['index'] + 1 and candidate['marker'] == previous['marker'] and
                abs(candidate['box'][0] - previous['box'][0]) <= height and
                -height * .2 <= candidate['box'][1] - previous['box'][3] <= height * 2)
        if not compatible:
            finish_list()
            group = []
        if candidate:
            group.append(candidate)

    # Labels are attached only to a unique same-column graphic on the same page.
    for row in list(items):
        if len(row.get('prov', [])) != 1:
            continue
        page = pages.get(row['prov'][0].get('page_no'))
        if not page:
            continue
        box = _bounds(row, page)
        label_pattern = r'\([A-Za-z0-9]{1,8}(?:[.-][A-Za-z0-9]{1,8}){0,3}\)' if row.get('_semantic_version')=='4.0' else r'\(\d{1,3}[a-z]?\)'
        if row.get('label') in {'text', 'paragraph'} and re.fullmatch(label_pattern, text(row)):
            candidates = []
            for eq in items:
                if eq.get('label') != 'formula' or len(eq.get('prov', [])) != 1:
                    continue
                eb = _bounds(eq, page)
                if eb and 0 <= box[0] - eb[2] < page['page_size'][0] * .25 and min(box[3], eb[3]) - max(box[1], eb[1]) >= min(box[3]-box[1], eb[3]-eb[1]) * .5:
                    candidates.append(eq)
            proof = lines(row, page)
            if len(candidates) == 1 and ''.join(r['text'] for r in proof).strip() == text(row):
                eq = candidates[0]
                eq['_equation_number'] = text(row)
                eq['prov'][0]['bbox'] = dict(zip(('l','t','r','b'), _union([box, _bounds(eq,page)])), coord_origin='TOPLEFT')
                items.remove(row)
                record('native_equation_number', [text(eq), text(row)], [text(eq) + ' ' + text(row)], page['page'], native_evidence=proof)
        elif row.get('label') == 'caption' and re.match(r'^\([a-z]\)\s+\S', text(row)):
            candidates = []
            for figure in items:
                if figure.get('label') != 'picture':
                    continue
                fb = _bounds(figure, page)
                if fb and 0 <= box[1] - fb[3] <= 24 and box[0] >= fb[0] - 10 and box[2] <= fb[2] + 10:
                    candidates.append(figure)
            if len(candidates) == 1:
                figure = candidates[0]
                refs = [r for r in figure.get('captions', []) if r.get('$ref') != row['self_ref']]
                figure['captions'] = [{'$ref': row['self_ref']}, *refs]
                record('native_subfigure_label', [text(row)], [text(row)], page['page'],
                    figure_ref=figure.get('self_ref'), caption_ref=row['self_ref'], bbox=box)

    # Ignore floating resources and marginal notes, never intervening body text
    # or headings. Native line edges must confirm both halves of the sentence.
    body = [r for r in items if r.get('label') not in {'picture','table','caption','footnote','page_header','page_footer'}]
    index = 0
    while index + 1 < len(body):
        first, second = body[index:index + 2]
        index += 1
        prose_pair = first.get('label') in {'text','paragraph'} and second.get('label') in {'text','paragraph'}
        list_pair = first.get('label') == 'list_item' and second.get('label') in {'text','paragraph'}
        reference_pair = (first.get('label') == second.get('label') == 'reference' and
                          re.match(r'^\[\d+\]\s+', text(first)) and not re.match(r'^\[\d+\]', text(second)))
        if first not in items or not (prose_pair or list_pair or reference_pair):
            continue
        if not first.get('prov') or not second.get('prov'):
            continue
        lp = pages.get(first['prov'][-1].get('page_no'))
        rp = pages.get(second['prov'][0].get('page_no'))
        if not lp or not rp:
            continue
        lb = _bounds({'prov': first['prov'][-1:]}, lp)
        rb = _bounds(second, rp)
        across_page = rp['page'] == lp['page'] + 1
        across_column = rp['page'] == lp['page'] and lb[2] < lp['page_size'][0] * .55 and rb[0] > lp['page_size'][0] * .45
        if not (across_page or across_column) or lb[3] < lp['page_size'][1] * .78:
            continue
        left_lines, right_lines = lines(first, lp, lb), lines(second, rp, rb)
        if not left_lines or not right_lines:
            continue
        if reference_pair:
            origin_page = pages.get(first['prov'][0].get('page_no'))
            origin_lines = lines(first, origin_page) if origin_page else []
            marker = re.match(r'^\[\d+\]', text(first))[0]
            if not origin_lines or not _line_edge(origin_lines)['text'].startswith(marker):
                continue
        left, right = text(first), text(second)
        left_edge, right_edge = _line_edge(left_lines, last=True), _line_edge(right_lines)
        terminal, initial = left_edge['text'].strip(), right_edge['text'].strip()
        # An opening acronym can finish a noun phrase across a column just as
        # ordinary lowercase prose can. Single-letter/number list markers are
        # deliberately excluded from this continuation pattern.
        head = re.match(r'([a-z][A-Za-z]*|[A-Z][A-Z0-9]{1,15}(?=\s+[a-z])|\([A-Z][A-Z0-9]{1,15}\)(?=\s+[a-z]))', initial)
        if not head or not right.startswith(head[1]):
            continue
        if not head[1][0].islower():
            height = right_edge['bbox'][3] - right_edge['bbox'][1]
            if right_edge['bbox'][0] - rb[0] > height * .6:
                continue  # An indented new paragraph is not continuation proof.
        split = re.search(r'([A-Za-z]+)[\-\x02\u00ad]$', terminal)
        merged = None
        repaired_tail = False
        if split:
            word = split[1] + head[1]
            # Some parsers complete a split word on the first page. Remove only
            # the duplicate second-page suffix proven by the original glyphs.
            ending = re.search(re.escape(word) + r'([.,;:]?)$', left)
            if ending:
                suffix = right[len(head[1]):]
                if ending[1] and suffix.startswith(ending[1]):
                    suffix = suffix[1:]
                merged = left + suffix
            elif re.search(re.escape(split[1]) + r'[\x02\u00ad]?$', left):
                merged = left.rstrip('\x02\u00ad') + right
            else:
                cut = _native_prefix_end(left, left_lines, lb, head[1])
                if cut is not None:
                    merged = left[:cut] + right
                    repaired_tail = True
        elif not re.search(r'[.!?:;。！？：；]$', terminal) and not re.search(r'[.!?:;。！？：；]$', left):
            tail = re.search(r'([A-Za-z]+)$', terminal)
            if tail and left.endswith(tail[1]):
                merged = left + ' ' + right
        if merged is None:
            continue
        before = [left, right]
        from .rich_ir import merge_semantics
        merge_semantics(first, second, separator=' ' if merged == left + ' ' + right else '')
        first['orig'] = first['text'] = merged
        first['prov'].extend(deepcopy(second['prov']))
        items.remove(second)
        body.pop(index)
        index -= 1
        record('native_reference_continuation' if reference_pair else 'native_paragraph_continuation', before, [merged], lp['page'],
            pages=[lp['page'], rp['page']], repaired_generated_tail=repaired_tail,
            native_evidence=([*left_lines, right_edge] if repaired_tail else [left_edge, right_edge]))
    return items, audit
