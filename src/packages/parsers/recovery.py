"""Bounded native/page recovery before building source IR; never uses a translator."""
from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
import re
import time

from packages.quality.issues import comparison_text
from .progress import report_progress

PROSE_LABELS = {'text', 'paragraph', 'list_item'}
COMPLEX_LABELS = {'table', 'picture', 'formula', 'code'}
RULE_VERSION = 'native-paragraph-recovery-v2'


def _bounds(item, page):
    for loc in item.get('prov', []):
        if loc.get('page_no') == page['page']:
            box = loc['bbox']
            left, top, right, bottom = (box[k] for k in ('l', 't', 'r', 'b'))
            if str(box.get('coord_origin', 'TOPLEFT')).upper().endswith('BOTTOMLEFT'):
                top, bottom = page['page_size'][1] - bottom, page['page_size'][1] - top
            return [left, min(top, bottom), right, max(top, bottom)]
    return None


def _overlap(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1])) / max(1, (a[2] - a[0]) * (a[3] - a[1]))


def _item(ref, label, text, bounds, page, **extra):
    return {'self_ref': ref, 'label': label, 'orig': text, 'text': text,
        'prov': [{'page_no': page['page'], 'bbox': dict(zip(('l', 't', 'r', 'b'), bounds), coord_origin='TOPLEFT')}], **extra}


def _compact(text):
    return ''.join(comparison_text(text).split())


def _matches(region, row):
    text = _compact(region['text'])
    original = _compact(row.get('orig', row.get('text', '')))
    # A PDF line's discretionary hyphen may be exposed as U+0002. Only
    # ignore a trailing marker when the remaining text exists in the parser
    # paragraph; this comparison never edits either source representation.
    if re.search(r'[^\W\d_][-\x02]$', text):
        text = text[:-1]
    return bool(text) and text in original


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _has_columns(regions, page_width):
    if not page_width:
        return False
    left = [r['bbox'] for r in regions if r['bbox'][2] <= page_width / 2]
    right = [r['bbox'] for r in regions if r['bbox'][0] >= page_width / 2]
    # Font changes can split every line into short runs; use their combined
    # extent on each side of the gutter, not the width of an individual run.
    return bool(left and right and all(_union(side)[2] - _union(side)[0] > page_width * .25 for side in (left, right)))


def _native_lines(regions, page_width=None):
    """Join adjacent font runs on one baseline, never across a column gap."""
    lines = []
    middle = page_width / 2 if page_width else None
    columns = _has_columns(regions, page_width)
    for region in sorted(regions, key=lambda r: (r['bbox'][1], r['bbox'][0])):
        box = region['bbox']
        candidates = []
        for line in lines:
            bounds = _union([r['bbox'] for r in line])
            if columns and (bounds[2] <= middle <= box[0] or box[2] <= middle <= bounds[0]):
                continue
            height = max(1, min(box[3] - box[1], bounds[3] - bounds[1]))
            overlap = min(box[3], bounds[3]) - max(box[1], bounds[1])
            gap = max(0, box[0] - bounds[2], bounds[0] - box[2])
            if overlap >= height * .5 and gap <= height * 1.5:
                candidates.append((gap, line))
        if candidates:
            min(candidates, key=lambda pair: pair[0])[1].append(region)
        else:
            lines.append([region])
    output = []
    for line in lines:
        line.sort(key=lambda r: r['bbox'][0])
        text = line[0]['text'].strip()
        for previous, region in zip(line, line[1:]):
            # Very close glyphs belong to one word (including style changes).
            height = max(1, min(previous['bbox'][3] - previous['bbox'][1], region['bbox'][3] - region['bbox'][1]))
            gap = region['bbox'][0] - previous['bbox'][2]
            text += (' ' if gap > height * .2 else '') + region['text'].strip()
        output.append({'text': text, 'bbox': _union([r['bbox'] for r in line])})
    return sorted(output, key=lambda r: (r['bbox'][1], r['bbox'][0]))


def _paragraph_text(lines):
    return comparison_text('\n'.join(line['text'] for line in lines))


def _repair_text(row, regions, page):
    if _has_columns(regions, page['page_size'][0]):
        return None  # A broad model box is not proof of a single paragraph.
    candidate = _paragraph_text(_native_lines(regions))
    original = row.get('orig', row.get('text', ''))
    changes = SequenceMatcher(None, original.split(), candidate.split(), autojunk=False).get_opcodes()
    # Native extraction is often less faithful for math, font runs and PDF
    # hyphens. Only accept an insertion that retains every existing token in
    # order; substitutions/deletions remain visible quality diagnostics.
    if original.strip() and any(tag == 'insert' for tag, *_ in changes) and all(tag in {'equal', 'insert'} for tag, *_ in changes):
        return candidate
    return None


def _new_paragraphs(regions, page):
    lines = _native_lines(regions, page['page_size'][0])
    ordered = _page_order([_item(str(i), 'text', line['text'], line['bbox'], page)
                           for i, line in enumerate(lines)], page)
    groups = []
    for row in ordered:
        line = lines[int(row['self_ref'])]
        box = line['bbox']
        previous = groups[-1][-1] if groups else None
        bounds = previous['bbox'] if previous else None
        height = max(1, box[3] - box[1])
        # A gap or indentation is a paragraph boundary. Unknown layout stays
        # separate rather than merging across columns, lists, or blank lines.
        continues = bounds and 0 <= box[1] - bounds[3] <= min(height, bounds[3] - bounds[1]) * .45
        continues = continues and abs(box[0] - bounds[0]) <= height * .5
        if continues:
            groups[-1].append(line)
        else:
            groups.append([line])
    return [_item(f'nb-native-{page["page"]}-{i}', 'text', _paragraph_text(group),
                  _union([line['bbox'] for line in group]), page) for i, group in enumerate(groups)]


def _page_order(items, page):
    """Native two-column order within bands separated by spanning content."""
    width = page['page_size'][0]
    boxes = [(row, _bounds(row, page)) for row in items]
    boxes = [(row, box) for row, box in boxes if box]
    left = [b for _, b in boxes if b[2] <= width * .55]
    right = [b for _, b in boxes if b[0] >= width * .45]
    two_columns = bool(left and right)
    spanning = sorted({b[1] for _, b in boxes if b[0] < width * .45 and b[2] > width * .55})
    def key(pair):
        row, box = pair
        if not two_columns:
            return (box[1], box[0])
        band = sum(y <= box[1] for y in spanning)
        span = box[0] < width * .45 and box[2] > width * .55
        column = -1 if span else 0 if (box[0] + box[2]) / 2 < width / 2 else 1
        return (band, column, box[1], box[0])
    return [row for row, _ in sorted(boxes, key=key)]


def recover_items(items, pages, *, local_reparse=None, remaining_seconds=None):
    result, audit = deepcopy(items), []
    remaining_seconds = remaining_seconds or (lambda: float('inf'))
    for page in pages:
        started, at = time.monotonic(), datetime.now(timezone.utc).isoformat()
        number = page['page']
        local = [row for row in result if _bounds(row, page)]
        native = [r for r in page.get('text_regions', []) if _compact(r['text'])]
        def record(action, before, after, **extra):
            audit.append({'origin': 'automatic_recovery', 'rule_version': RULE_VERSION, 'page': number,
                'action': action, 'before': before, 'after': after, 'started_at': at,
                'finished_at': datetime.now(timezone.utc).isoformat(), 'elapsed_ms': int((time.monotonic() - started) * 1000),
                'model': None, **extra})
        # A configuration-like token is corrected only against a unique native
        # token in this original table. Do not guess decimal values or words.
        for row in local:
            if row.get('label') != 'table':
                continue
            bounds = _bounds(row, page)
            original = ' '.join(r['text'] for r in native if _overlap(r['bbox'], bounds) >= .6)
            tokens = set(re.findall(r'(?<![\w.])\d+(?:[-.]\d+){2,}(?![\w.])', original))
            for cell in row.get('data', {}).get('table_cells', []):
                before = cell.get('text', '')
                matches = [t for t in tokens if re.sub(r'[-.]', '', t) == re.sub(r'[-.]', '', before)]
                if len(matches) == 1 and before != matches[0] and re.fullmatch(r'\d+(?:[-.]\d+){2,}', before):
                    cell['text'] = matches[0]
                    record('native_table_token', before, matches[0], item_ref=row.get('self_ref'))
        prose_native = []
        for region in native:
            complex_or_kept = [row for row in local if row.get('label') not in PROSE_LABELS and
                _overlap(region['bbox'], _bounds(row, page)) >= .6]
            if complex_or_kept:
                continue
            prose_native.append(region)
        prose = [row for row in local if row.get('label') in PROSE_LABELS]
        assigned = {row['self_ref']: [] for row in prose}
        outside = []
        for region in prose_native:
            owners = [row for row in prose if _overlap(region['bbox'], _bounds(row, page)) >= .6]
            if not owners:
                # Model rectangles sometimes stop before the final baseline.
                # Nearby exact text is proof of coverage, not another paragraph.
                box = region['bbox']; height = max(1, box[3] - box[1])
                for row in prose:
                    bounds = _bounds(row, page)
                    aligned = min(box[2], bounds[2]) - max(box[0], bounds[0]) >= (box[2] - box[0]) * .6
                    if aligned and bounds[1] - height * 1.5 <= box[1] <= bounds[3] + height * 1.5 and _matches(region, row):
                        owners.append(row)
            if owners:
                owner = min(owners, key=lambda row: (_bounds(row, page)[2] - _bounds(row, page)[0]) *
                            (_bounds(row, page)[3] - _bounds(row, page)[1]))
                assigned[owner['self_ref']].append(region)
            else:
                outside.append(region)
        damaged = [row for row in prose if any(not _matches(r, row) for r in assigned[row['self_ref']])]
        missing = outside + [r for row in damaged for r in assigned[row['self_ref']] if not _matches(r, row)]
        crossing = [row for row in damaged if len(row.get('prov', [])) > 1]
        if missing:
            report_progress('recovery_started', page=number, phase='native_text')
            before = [row.get('orig', row.get('text', '')) for row in prose]
            repairs = [(row, _repair_text(row, assigned[row['self_ref']], page)) for row in damaged if row not in crossing]
            repaired = [row for row, text in repairs if text is not None]
            uncertain = [row for row, text in repairs if text is None] + crossing
            for row, text in repairs:
                # Preserve this parser paragraph's identity and geometry.
                # Full native evidence within it replaces only this paragraph.
                if text is not None:
                    row['orig'] = row['text'] = text
            replacement = _new_paragraphs(outside, page)
            result.extend(replacement)
            if repaired or replacement:
                local = [row for row in result if _bounds(row, page)]
                ordered = _page_order(local, page)
                first = min((result.index(row) for row in local), default=len(result))
                result = [row for row in result if row not in local]
                result[first:first] = ordered
                record('native_page_recovery', before,
                       [row.get('orig', row.get('text', '')) for row in ordered if row.get('label') in PROSE_LABELS],
                       recovered_regions=len(missing), repaired_paragraphs=len(repaired), added_paragraphs=len(replacement))
            if uncertain:
                unchanged = [row.get('orig', row.get('text', '')) for row in uncertain]
                record('native_recovery_uncertain', unchanged, unchanged, result='retained_page')
            report_progress('recovery_completed', page=number, phase='native_text')
        readable = any(row.get('orig', row.get('text', '')).strip() for row in local if row.get('label') not in COMPLEX_LABELS)
        if not native and not readable and local_reparse is not None and remaining_seconds() > 1:
            report_progress('recovery_started', page=number, phase='local_parse')
            try:
                # Exactly one additional local attempt per missing page.
                retry = local_reparse(number) or []
                retry = [row for row in retry if _bounds(row, page)]
                result.extend(retry)
                local.extend(retry)
                readable = any(row.get('orig', row.get('text', '')).strip() for row in retry if row.get('label') not in COMPLEX_LABELS)
                record('local_page_reparse', [], [row.get('orig', row.get('text', '')) for row in retry],
                    attempts=1, result='recovered' if readable else 'no_text', model=getattr(local_reparse, 'model_identity', None))
            except Exception:
                record('local_page_reparse', [], [], attempts=1, result='failed', model=getattr(local_reparse, 'model_identity', None))
            report_progress('recovery_completed', page=number, phase='local_parse')
        if not readable and not native or page.get('scan_suspected') or (missing and crossing):
            width, height = page['page_size']
            if not any(row.get('_nb_page_fallback') for row in local):
                result.append(_item(f'nb-page-{number}', 'picture', '', [0, 0, width, height], page, _nb_page_fallback=True))
                record('page_image_fallback', [], [], result='original_page')
    # A missing title does not discard every usable page. Promote actual source
    # text for navigation; an image-only PDF has an explicitly empty title.
    if not any(row.get('label') in {'title', 'section_header'} and row.get('orig', row.get('text', '')).strip() for row in result):
        first = next((row for row in result if row.get('label') in PROSE_LABELS and row.get('text', '').strip()), None)
        if first:
            first['label'] = 'title'
            first['_nb_navigation_title'] = True
        elif pages:
            result.insert(0, _item('nb-navigation-title', 'title', '', [0, 0, 0, 0], pages[0], _nb_navigation_title=True))
    # Keep stable page order without changing unaffected within-page model order.
    result.sort(key=lambda row: min((p['page_no'] for p in row.get('prov', [])), default=0))
    return result, audit
