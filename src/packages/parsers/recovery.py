"""Bounded native/page recovery before building source IR; never uses a translator."""
from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
import re
import time

from packages.quality.issues import comparison_text
from .progress import report_progress
from .table_html import recover_cell_line_breaks

PROSE_LABELS = {'text', 'paragraph', 'list_item'}
COMPLEX_LABELS = {'table', 'picture', 'formula', 'code'}
RULE_VERSION = 'native-paragraph-recovery-v3'


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


def _furniture_label(text, bounds, page):
    """Recognize narrow metadata patterns only in their original PDF margins."""
    width, height = page['page_size']
    text = text.strip()
    if re.fullmatch(r'[0-9]{1,4}', text):
        if bounds[1] >= height * .94:
            return 'page_footer'
        if bounds[3] <= height * .06:
            return 'page_header'
    side_margin = bounds[2] <= width * .08 or bounds[0] >= width * .92
    if side_margin and re.fullmatch(
            r'arXiv:\s*(?:\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})(?:v\d+)?'
            r'(?:\s*\[[\w.-]+\])?(?:\s+\d{1,2}\s+[A-Za-z]{3}\s+\d{4})?', text):
        return 'page_header'
    return None


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
    native = '\n'.join(line['text'] for line in lines)
    native = re.sub(r'(?<=[^\W\d_])[\x02\u00ad]\s*\n\s*(?=[^\W\d_])', '', native)
    return comparison_text(native)


def _complete_native_coverage(lines, bounds):
    """Require text to cover the paragraph without room for a missing baseline."""
    if len(lines) < 2:
        return False
    height = max(line['bbox'][3] - line['bbox'][1] for line in lines)
    return (lines[0]['bbox'][1] - bounds[1] <= height * .75 and
            bounds[3] - lines[-1]['bbox'][3] <= height * .75 and
            all(b['bbox'][1] - a['bbox'][3] <= height * .75 for a, b in zip(lines, lines[1:])))


def _repair_reference_metadata(original, native_lines, bounds):
    if not _complete_native_coverage(native_lines, bounds):
        return None
    native = _paragraph_text(native_lines)
    markers = [re.match(r'^\[(\d{1,4})\]\s+', value) for value in (original, native)]
    # Initials contain a single letter; a full name followed by a capitalized
    # title bounds the author list in this numbered bibliography format.
    ends = [re.search(r'[A-Za-z][A-Za-z-]{1,}\.\s+(?=[A-Z])', value) for value in (original, native)]
    if not all(markers) or not all(ends):
        return None
    def core(value):
        return ''.join(c for c in value if c.isalnum())
    bodies = [core(value[end.end():]) for value, end in zip((original, native), ends)]
    if len(bodies[0]) < 80 or bodies[0] != bodies[1]:
        return None
    positions = [[index for index, c in enumerate(value) if c.isalnum()] for value in (original, native)]
    changes = [entry for entry in SequenceMatcher(None, core(original), core(native), autojunk=False).get_opcodes()
               if entry[0] != 'equal']
    if not 1 <= len(changes) <= 2:
        return None
    corrected = list(original)
    for tag, a, b, c, d in changes:
        if tag != 'replace' or b - a != 1 or d - c != 1:
            return None
        left, right = positions[0][a], positions[1][c]
        if left >= ends[0].end() or right >= ends[1].end():
            return None
        old, new = original[left], native[right]
        numeral = (old.isdigit() and new.isdigit() and
                   markers[0].start(1) <= left < markers[0].end(1) and
                   markers[1].start(1) <= right < markers[1].end(1))
        if not numeral and not (old.isalpha() and new.isalpha()):
            return None
        corrected[left] = new
    return ''.join(corrected)


def _repair_text(row, regions, page):
    if _has_columns(regions, page['page_size'][0]):
        return None  # A broad model box is not proof of a single paragraph.
    native_lines = _native_lines(regions)
    candidate = _paragraph_text(native_lines)
    original = row.get('orig', row.get('text', ''))
    changes = SequenceMatcher(None, original.split(), candidate.split(), autojunk=False).get_opcodes()
    # Native extraction is often less faithful for math, font runs and PDF
    # hyphens. Only accept an insertion that retains every existing token in
    # order; substitutions/deletions remain visible quality diagnostics.
    if original.strip() and any(tag == 'insert' for tag, *_ in changes) and all(tag in {'equal', 'insert'} for tag, *_ in changes):
        return candidate
    # A long paragraph with one closely related wrong word can be corrected
    # mechanically. Keep every other model token (including its formatting),
    # and reject math, sparse evidence and unrelated lexical substitutions.
    replacements = [change for change in changes if change[0] != 'equal']
    tokens = list(re.finditer(r'\S+', original))
    if (len(tokens) >= 12 and len(replacements) == 1 and not re.search(r'[$\\^_=<>]', original + candidate)
            and _complete_native_coverage(native_lines, _bounds(row, page))):
        tag, a, b, c, d = replacements[0]
        if tag == 'replace' and b - a == d - c == 1:
            old, new = tokens[a][0], candidate.split()[c]
            prefix = 0
            for left, right in zip(old, new):
                if left != right:
                    break
                prefix += 1
            letters = [change for change in SequenceMatcher(None, old, new, autojunk=False).get_opcodes() if change[0] != 'equal']
            one_extra = (len(letters) == 1 and letters[0][0] in {'insert', 'delete'} and
                         max(letters[0][2] - letters[0][1], letters[0][4] - letters[0][3]) == 1)
            if (re.fullmatch(r'[A-Za-z]{7,}', old) and re.fullmatch(r'[A-Za-z]{7,}', new) and
                    prefix >= 6 and (prefix >= max(len(old), len(new)) * .7 or one_extra)):
                return original[:tokens[a].start()] + new + original[tokens[a].end():]
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
        # Paddle may call folios and rotated arXiv stamps ordinary text. Keep
        # their original region as furniture so the independent coverage ledger
        # can justify the exclusion, rather than dropping the PDF evidence.
        for row in local:
            if row.get('label') not in {'text', 'paragraph'} or len(row.get('prov', [])) != 1:
                continue
            bounds = _bounds(row, page)
            text = row.get('orig', row.get('text', ''))
            label = _furniture_label(text, bounds, page)
            proof = [r for r in native if _overlap(r['bbox'], bounds) >= .6]
            if label and proof and _compact(' '.join(r['text'] for r in proof)) == _compact(text):
                row['label'] = label
                record('native_page_furniture', text, [], item_ref=row.get('self_ref'),
                       label=label, native_evidence=proof)
        # Native recovery must not reinsert furniture omitted by the model.
        for line in _native_lines(native, page['page_size'][0]):
            label = _furniture_label(line['text'], line['bbox'], page)
            if not label or any(_overlap(line['bbox'], _bounds(row, page)) >= .6 for row in local):
                continue
            row = _item(f'nb-furniture-{number}-{len(local)}', label, line['text'], line['bbox'], page)
            result.append(row)
            local.append(row)
            record('native_page_furniture', line['text'], [], item_ref=row['self_ref'],
                   label=label, native_evidence=[line])
        for row in local:
            if row.get('label') != 'reference' or len(row.get('prov', [])) != 1:
                continue
            bounds = _bounds(row, page)
            proof = [r for r in native if _overlap(r['bbox'], bounds) >= .6]
            original = row.get('orig', row.get('text', ''))
            repaired = _repair_reference_metadata(original, _native_lines(proof), bounds)
            if repaired is not None:
                row['orig'] = row['text'] = repaired
                record('native_reference_metadata', original, repaired, item_ref=row.get('self_ref'),
                       native_evidence=proof)
        # A configuration-like token is corrected only against a unique native
        # token in this original table. Do not guess decimal values or words.
        for row in local:
            if row.get('label') != 'table':
                continue
            bounds = _bounds(row, page)
            table_native = [r for r in native if _overlap(r['bbox'], bounds) >= .6]
            original = ' '.join(r['text'] for r in table_native)
            table_lines = _native_lines(table_native)
            tokens = set(re.findall(r'(?<![\w.])\d+(?:[-.]\d+){2,}(?![\w.])', original))
            for cell in row.get('data', {}).get('table_cells', []):
                before = cell.get('text', '')
                line_breaks = recover_cell_line_breaks(before, table_lines)
                if line_breaks:
                    cell['text'], proof = line_breaks
                    record('native_table_linebreak', before, cell['text'],
                           item_ref=row.get('self_ref'), native_evidence=proof)
                    before = cell['text']
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
                    original = row.get('orig', row.get('text', ''))
                    changes = SequenceMatcher(None, original.split(), text.split(), autojunk=False).get_opcodes()
                    if any(tag == 'replace' for tag, *_ in changes):
                        record('native_prose_token', original, text, item_ref=row.get('self_ref'),
                               native_evidence=assigned[row['self_ref']])
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
    from .layout_recovery import recover_layout
    result, layout_audit = recover_layout(result, pages)
    audit.extend(layout_audit)
    return result, audit
