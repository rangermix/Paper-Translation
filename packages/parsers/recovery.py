"""Bounded native/page recovery before building source IR; never uses a translator."""
from copy import deepcopy
from datetime import datetime, timezone
import re
import time

from packages.quality.issues import comparison_text
from .progress import report_progress

PROSE_LABELS = {'text', 'paragraph', 'list_item'}
COMPLEX_LABELS = {'table', 'picture', 'formula', 'code'}
RULE_VERSION = 'native-page-recovery-v1'


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
            if any(row.get('label') in COMPLEX_LABELS or _compact(region['text']) in _compact(row.get('orig', row.get('text', '')))
                   for row in complex_or_kept):
                continue
            prose_native.append(region)
        missing = [r for r in prose_native if not any(_overlap(r['bbox'], _bounds(row, page)) >= .6 and
            _compact(r['text']) in _compact(row.get('orig', row.get('text', ''))) for row in local)]
        if missing:
            report_progress('recovery_started', page=number, phase='native_text')
            # Reconstruct page-local prose once, retaining complex containers,
            # headings and captions. This avoids adding fragments twice under
            # a broad but incomplete paragraph rectangle.
            removable = [row for row in local if row.get('label') in PROSE_LABELS and len(row.get('prov', [])) == 1]
            crossing = [row for row in local if row.get('label') in PROSE_LABELS and len(row.get('prov', [])) > 1]
            if not crossing:
                replacement = [_item(f'nb-native-{number}-{index}', 'text', region['text'], region['bbox'], page)
                               for index, region in enumerate(prose_native)]
                before = [row.get('orig', row.get('text', '')) for row in removable]
                result = [row for row in result if row not in removable]
                result.extend(replacement)
                local = [row for row in result if _bounds(row, page)]
                ordered = _page_order(local, page)
                first = min((result.index(row) for row in local), default=len(result))
                result = [row for row in result if row not in local]
                result[first:first] = ordered
                record('native_page_recovery', before, [row['text'] for row in replacement], recovered_regions=len(missing))
            else:
                record('native_recovery_uncertain', [], [], result='retained_page')
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
