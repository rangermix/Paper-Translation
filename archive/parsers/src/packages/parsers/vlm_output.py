"""Convert OCR output to IR items; generated markup is data, never a webpage."""
import html
import math
import re

from packages.ir import strict_loads
from .inspect import PDFError
from .table_html import parse_table_html

LABELS = {
    'text': 'text', 'paragraph': 'text', 'title': 'title', 'sectionheader': 'section_header',
    'section-header': 'section_header', 'header': 'page_header', 'footer': 'page_footer',
    'pageheader': 'page_header', 'page-header': 'page_header', 'pagefooter': 'page_footer',
    'page-footer': 'page_footer', 'caption': 'caption', 'figure_caption': 'caption',
    'table_caption': 'caption', 'formula_caption': 'caption', 'footnote': 'footnote',
    'page_footnote': 'footnote', 'figure_footnote': 'footnote', 'table_footnote': 'footnote',
    'table': 'table', 'equation': 'formula', 'equation-block': 'formula', 'formula': 'formula',
    'code': 'code', 'code-block': 'code', 'image': 'picture', 'picture': 'picture',
    'figure': 'picture', 'diagram': 'picture', 'bibliography': 'reference',
    'ref_text': 'reference', 'page_number': 'page_footer', 'image_caption': 'caption',
    'code_caption': 'caption', 'image_footnote': 'footnote', 'algorithm': 'code',
}


def strip_fences(value):
    if not isinstance(value, str) or len(value) > 1_000_000:
        raise PDFError('PARSER_OUTPUT_INVALID')
    value = value.strip()
    if value.startswith('```'):
        value = re.sub(r'^```[^\n]*\n', '', value)
        value = re.sub(r'\n```\s*$', '', value)
    return value


def bbox(value, page, scale=1000):
    if isinstance(value, str):
        value = [float(x) for x in value.replace(',', ' ').split()]
    if (not isinstance(value, (list, tuple)) or len(value) != 4 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value)
            or not 0 <= value[0] < value[2] <= scale or not 0 <= value[1] < value[3] <= scale):
        raise PDFError('PARSER_OUTPUT_INVALID')
    width, height = page['page_size']
    return [value[0] / scale * width, value[1] / scale * height,
            value[2] / scale * width, value[3] / scale * height]


def item(label, text, bounds, page, index, data=None):
    value = {'self_ref': f'vlm-{page["page"]}-{index}', 'label': label, 'text': text, 'orig': text,
             'prov': [{'page_no': page['page'], 'bbox': dict(zip(('l', 't', 'r', 'b'), bounds), coord_origin='TOPLEFT')}]}
    if data is not None:
        value['data'] = data
    return value


def plain_markup(value):
    from lxml import html as parser
    tree = parser.fragment_fromstring(value or '<span></span>', create_parent=True)
    for node in tree.xpath('.//script|.//style|.//iframe|.//object|.//img'):
        node.drop_tree()
    for node in tree.xpath('.//br'):
        node.tail = '\n' + (node.tail or '')
    for node in tree.xpath('.//p|.//li|.//pre|.//div'):
        node.tail = '\n' + (node.tail or '')
    return tree.text_content().strip()


def html_items(raw, page):
    from lxml import html as parser
    value = strip_fences(raw)
    tree = parser.fragment_fromstring(value or '<span></span>', create_parent=True)
    blocks = tree.xpath('.//div[@data-bbox][@data-label]')
    if len(blocks) > 1000:
        raise PDFError('PARSER_OUTPUT_INVALID')
    result = []
    for node in blocks:
        if any(parent.get('data-bbox') for parent in node.iterancestors()):
            continue
        name = node.get('data-label').lower()
        if name in ('blank-page', 'blankpage'):
            continue
        label = LABELS.get(name, 'text')
        bounds = bbox(node.get('data-bbox'), page)
        content = ''.join(parser.tostring(child, encoding='unicode') for child in node)
        text = plain_markup(parser.tostring(node, encoding='unicode'))
        data = None
        if label == 'picture':
            text = ''  # Image descriptions are not evidence of printed source text.
        elif label == 'table':
            tables = node.xpath('.//table')
            data = parse_table_html(parser.tostring(tables[0], encoding='unicode')) if len(tables) == 1 else None
        elif label == 'formula':
            text = plain_markup(content or node.text or '')
        result.append(item(label, text, bounds, page, len(result), data))
    if not result and value:
        raise PDFError('PARSER_OUTPUT_INVALID')
    return result


def json_items(raw, page):
    data = strict_loads(strip_fences(raw))
    if isinstance(data, dict):
        for key in ('layout', 'elements', 'blocks', 'layout_elements'):
            if key in data:
                data = data[key]
                break
    if not isinstance(data, list) or len(data) > 1000:
        raise PDFError('PARSER_OUTPUT_INVALID')
    result = []
    for entry in data:
        if not isinstance(entry, dict):
            raise PDFError('PARSER_OUTPUT_INVALID')
        label = LABELS.get(str(entry.get('category', entry.get('label', 'text'))).lower(), 'text')
        text = entry.get('text', entry.get('content', ''))
        if not isinstance(text, str):
            raise PDFError('PARSER_OUTPUT_INVALID')
        bounds = bbox(entry.get('bbox'), page)
        table = parse_table_html(text) if label == 'table' else None
        if label == 'picture':
            text = ''
        result.append(item(label, text, bounds, page, len(result), table))
    return result


def otsl_table(value):
    """Decode a rectangular OTSL grid, including spans; malformed grids retain imagery."""
    tokens = re.split(r'(<(?:fcel|ecel|lcel|ucel|xcel|nl)>)', value.strip())
    rows, row, current = [], [], None
    for token in tokens:
        if not token:
            continue
        if token == '<nl>':
            if not row:
                return None
            rows.append(row)
            row, current = [], None
        elif re.fullmatch(r'<(?:fcel|ecel|lcel|ucel|xcel)>', token):
            current = {'kind': token, 'text': ''}
            row.append(current)
        elif current and current['kind'] == '<fcel>':
            current['text'] += token
        elif token.strip():
            return None
    if row:
        rows.append(row)
    if not rows or len(rows) > 1000 or not rows[0] or len(rows) * len(rows[0]) > 10000:
        return None
    columns = len(rows[0])
    if any(len(row) != columns for row in rows):
        return None
    owners, cells = {}, []
    for r, row in enumerate(rows):
        for c, entry in enumerate(row):
            kind = entry['kind']
            if kind in ('<fcel>', '<ecel>'):
                cell = {'text': html.unescape(entry['text']).strip(), 'start_row_offset_idx': r,
                        'end_row_offset_idx': r + 1, 'start_col_offset_idx': c, 'end_col_offset_idx': c + 1}
                cells.append(cell)
            else:
                previous = (r, c - 1) if kind == '<lcel>' else (r - 1, c)
                cell = owners.get(previous)
                if cell is None or kind == '<xcel>' and owners.get((r, c - 1)) is not cell:
                    return None
                cell['end_row_offset_idx'] = max(cell['end_row_offset_idx'], r + 1)
                cell['end_col_offset_idx'] = max(cell['end_col_offset_idx'], c + 1)
            owners[(r, c)] = cell
    for cell in cells:
        cell['row_span'] = cell['end_row_offset_idx'] - cell['start_row_offset_idx']
        cell['col_span'] = cell['end_col_offset_idx'] - cell['start_col_offset_idx']
        if any(owners.get((r, c)) is not cell
               for r in range(cell['start_row_offset_idx'], cell['end_row_offset_idx'])
               for c in range(cell['start_col_offset_idx'], cell['end_col_offset_idx'])):
            return None
    return {'num_rows': len(rows), 'num_cols': columns, 'table_cells': cells}


def markdown_items(raw, page):
    """Page-level provenance when the model supplies no block coordinates."""
    value = strip_fences(raw)
    width, height = page['page_size']
    result = []
    for chunk in re.split(r'\n\s*\n', value):
        chunk = chunk.strip()
        if not chunk:
            continue
        label, text, data = 'text', chunk, None
        if '<fcel>' in chunk or '<ecel>' in chunk:
            label, data = 'table', otsl_table(chunk)
        elif chunk.startswith('$$') or chunk.startswith('\\['):
            label = 'formula'
        elif chunk.startswith('```'):
            label = 'code'
            text = strip_fences(chunk)
        elif re.match(r'^#{1,6}\s', chunk):
            label, text = 'section_header', re.sub(r'^#{1,6}\s+', '', chunk)
        # Do not follow or fetch model-created media references.
        text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
        result.append(item(label, text, [0, 0, width, height], page, len(result), data))
    return result
