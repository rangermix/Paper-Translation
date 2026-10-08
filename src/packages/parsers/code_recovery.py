"""Keep printed code literal, using PDF geometry instead of invented syntax."""
from copy import deepcopy
from datetime import datetime, timezone
import re

from .fidelity import overlap, union
from .semantic import node

VERSION = 'native-code-layout-v1'


def _compact(value):
    return ''.join(c for c in value if not c.isspace())


def _code_leaves(tree):
    if not tree:
        return []
    return ([tree] if tree['kind'] == 'code' else []) + [
        leaf for child in tree['children'] for leaf in _code_leaves(child)]


def _baselines(regions):
    """Group a listing's font/operator runs by vertical overlap, then x order.

    Operators have short glyph boxes and must not create independent lines.
    No punctuation or whitespace is reconstructed here: this is only evidence
    for where to split an otherwise exactly matching model transcription.
    """
    lines = []
    for region in sorted(regions, key=lambda r: (r['bbox'][1], r['bbox'][0])):
        box = region['bbox']
        candidates = []
        for line in lines:
            bounds = union([r['bbox'] for r in line])
            shared = min(box[3], bounds[3]) - max(box[1], bounds[1])
            height = min(box[3] - box[1], bounds[3] - bounds[1])
            if height > 0 and shared >= height * .5:
                candidates.append(line)
        if len(candidates) == 1:
            candidates[0].append(region)
        else:
            lines.append([region])
    return [{'text': ''.join(r['text'].strip() for r in sorted(line, key=lambda r: r['bbox'][0])),
             'parts': sorted(line, key=lambda r: r['bbox'][0]),
             'bbox': union([r['bbox'] for r in line])} for line in lines]


def _native_code_layout(original, lines):
    """Split exact matching characters at native baselines, retaining spaces.

    Existing indentation survives if its line boundaries agree with the PDF.
    Flattened indented listings fall back to an image; inferring indentation
    from a proportional font could change a program's meaning.
    """
    if not lines or len(original) > 16000:
        return None
    native = [_compact(line['text']) for line in lines]
    if not all(native) or _compact(original) != ''.join(native):
        return None
    positions = [i for i, c in enumerate(original) if not c.isspace()]
    offset = 0
    for line in lines:
        previous = None
        for span in line['parts']:
            part = span['text'].strip()
            length = len(_compact(part))
            if not length or '\n' in part or '\r' in part:
                return None
            # Whitespace inside an independently extracted span is source
            # evidence too, especially inside strings and comments. Do not
            # accept matching characters after losing a literal space.
            if original[positions[offset]:positions[offset + length - 1] + 1] != part:
                return None
            if previous and re.match(r'\w', part) and re.search(r'\w$', previous['text'].strip()):
                # Font/color changes can split adjacent code tokens. Require
                # a native word gap for a separator (or clear adjacency for
                # no separator), so return + x cannot become returnx.
                gap = span['bbox'][0] - previous['bbox'][2]
                height = min(span['bbox'][3] - span['bbox'][1], previous['bbox'][3] - previous['bbox'][1])
                separator = original[positions[offset - 1] + 1:positions[offset]]
                explicit_space = previous['text'].endswith((' ', '\t')) or span['text'].startswith((' ', '\t'))
                if explicit_space or gap >= height * .4:
                    if not separator:
                        return None
                elif gap <= height * .15:
                    if separator:
                        return None
                else:
                    return None
            offset += length
            previous = span
    existing = [line for line in original.splitlines() if line.strip()]
    if [_compact(line) for line in existing] == native:
        # Confirm relative indentation from native positions. In particular,
        # a model's unindented multi-line output is not proof that the PDF is
        # unindented. Exact tab width cannot be established from glyph boxes.
        tolerance = max(1, min(line['bbox'][3] - line['bbox'][1] for line in lines) * .3)
        levels = {}
        for printed, line in zip(existing, lines):
            prefix = printed[:len(printed) - len(printed.lstrip(' \t'))]
            if '\t' in prefix:
                return None
            levels.setdefault(len(prefix), []).append(line['bbox'][0])
        previous = None
        for _, positions in sorted(levels.items()):
            if max(positions) - min(positions) > tolerance or previous is not None and min(positions) <= previous + tolerance:
                return None
            previous = max(positions)
        return original.strip('\r\n')
    lefts = [line['bbox'][0] for line in lines]
    height = min(line['bbox'][3] - line['bbox'][1] for line in lines)
    if max(lefts) - min(lefts) > max(1, height * .3):
        return None
    output = []
    offset = 0
    for line in native:
        end = offset + len(line)
        output.append(original[positions[offset]:positions[end - 1] + 1])
        offset = end
    return '\n'.join(output)


def _looks_like_code(lines):
    """Recognize complete native statements, never code mentioned in prose."""
    if len(lines) < 2:
        return False
    patterns = (r'^(?:import\s+\w|from\s+\w.*\s+import\s|def\s+\w+\s*\(|class\s+\w)',
                r'^(?:[A-Za-z_]\w*\s*,\s*)*[A-Za-z_]\w*\s*=\s*[^=]',
                r'^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\s*\(',
                r'^(?:for\s+.+\s+in\s+.+|if\s+.+|while\s+.+):$')
    # Native spans omit spaces at font boundaries; statement punctuation and
    # assignment still corroborate code even when import/def cannot match.
    strong = sum(any(re.match(pattern, line['text'].strip()) for pattern in patterns) for line in lines)
    return strong >= 2 and strong >= len(lines) * .6


def recover_code_regions(items, pages):
    from .recovery import _bounds
    pages = {page['page']: page for page in pages}
    audit = []
    for row in items:
        if len(row.get('prov', [])) != 1:
            continue
        page = pages.get(row['prov'][0]['page_no'])
        if not page:
            continue
        tree = row.get('_semantic')
        leaves = _code_leaves(tree)
        explicit = row.get('label') == 'code' or bool(leaves)
        if not explicit and row.get('label') not in {'text', 'paragraph'}:
            continue
        bounds = _bounds(row, page)
        # Use a unique native form as the crop boundary. It includes arrows,
        # annotations and omitted code while keeping neighbouring prose out.
        graphics = [r['bbox'] for r in page.get('graphic_regions', []) + page.get('image_regions', [])
                    if overlap(bounds, r['bbox']) >= .65 and overlap(r['bbox'], bounds) >= .65]
        if len(graphics) > 1:
            continue
        crop = graphics[0] if graphics else bounds
        proof = [r for r in page.get('text_regions', []) if overlap(r['bbox'], crop) >= .9 and r['text'].strip()]
        if len(proof) > 1000 or sum(len(r['text']) for r in proof) > 16000:
            continue
        lines = _baselines(proof)
        if not explicit and (not graphics or not _looks_like_code(lines)):
            continue
        if not explicit and tree and (tree['children'] or any(r['type'] != 'text' for r in tree['runs'])):
            continue
        original = row.get('_code_model_transcription', tree['text'] if tree else row.get('text', row.get('orig', '')))
        # With no native text, keep normal code parsing available for scans.
        # A native form still offers a complete, literal rendition of a
        # complex multi-part listing whose semantic children share one box.
        if not proof and not graphics:
            continue
        plain = _native_code_layout(original, lines)
        if tree and tree['kind'] != 'code' and leaves:
            plain = None
        if plain is None and not explicit:
            continue
        # A containing layout block may include unrelated prose/list content.
        # Only a native graphic can prove that it is one indivisible visual
        # listing; otherwise preserve the existing semantic structure.
        if plain is None and not graphics:
            continue
        before = original
        path = (tree or {}).get('path', '/native')
        attrs = deepcopy((tree or {}).get('attrs', {}))
        row['prov'][0]['bbox'] = dict(zip(('l', 't', 'r', 'b'), crop), coord_origin='TOPLEFT')
        if plain is not None:
            row.update(label='code', orig=plain, text=plain, _native_code=True)
            row['_semantic'] = node('code', [{'type':'code', 'text':plain, 'path':'/native'}], attrs=attrs, path='/native')
            action = 'native_code_layout'
        else:
            attrs.setdefault('annotations', []).append({'kind':'code_transcription',
                'value':before[:16000], 'output_path':path})
            notes = [child for child in (tree or {}).get('children', []) if child['kind'] in {'caption', 'footnote'}]
            row.update(label='picture', orig='', text='')
            row['_semantic'] = node('figure', children=notes, attrs=attrs, path=path)
            action = 'native_code_original_raster'
        at = datetime.now(timezone.utc).isoformat()
        audit.append(dict(origin='automatic_recovery', rule_version=VERSION, page=page['page'],
            action=action, before=before, after=plain or '', item_ref=row.get('self_ref'),
            started_at=at, finished_at=at, elapsed_ms=0, model=None,
            native_evidence=proof, original_bounds=bounds, recovered_bounds=crop))
    return items, audit
