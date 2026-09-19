"""Evidence-bound relationships across PDF page/column and graphic boundaries."""
from copy import deepcopy
from datetime import datetime, timezone
import re

from .recovery import _bounds, _native_lines, _overlap, _union

VERSION = 'native-layout-relations-v1'


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
        return _native_lines([r for r in page.get('text_regions', []) if bounds and _overlap(r['bbox'], bounds) >= .6])

    # Labels are attached only to a unique same-column graphic on the same page.
    for row in list(items):
        if len(row.get('prov', [])) != 1:
            continue
        page = pages.get(row['prov'][0].get('page_no'))
        if not page:
            continue
        box = _bounds(row, page)
        if row.get('label') in {'text', 'paragraph'} and re.fullmatch(r'\(\d{1,3}[a-z]?\)', text(row)):
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
        if first not in items or first.get('label') not in {'text','paragraph'} or second.get('label') not in {'text','paragraph'}:
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
        left, right = text(first), text(second)
        terminal, initial = left_lines[-1]['text'].strip(), right_lines[0]['text'].strip()
        head = re.match(r'([a-z][A-Za-z]*)', initial)
        if not head or not right.startswith(head[1]):
            continue
        split = re.search(r'([A-Za-z]+)[\-\x02\u00ad]$', terminal)
        merged = None
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
        elif not re.search(r'[.!?:;。！？：；]$', terminal) and not re.search(r'[.!?:;。！？：；]$', left):
            tail = re.search(r'([A-Za-z]+)$', terminal)
            if tail and left.endswith(tail[1]):
                merged = left + ' ' + right
        if merged is None:
            continue
        before = [left, right]
        first['orig'] = first['text'] = merged
        first['prov'].extend(deepcopy(second['prov']))
        items.remove(second)
        body.pop(index)
        index -= 1
        record('native_paragraph_continuation', before, [merged], lp['page'],
            pages=[lp['page'], rp['page']], native_evidence=[left_lines[-1], right_lines[0]])
    return items, audit
