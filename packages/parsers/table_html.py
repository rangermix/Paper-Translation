"""Decode one bounded table into data. Model HTML is never rendered or executed."""
from html.parser import HTMLParser
import re

TABLE_HTML_VERSION = 'paddle-table-html-v1'
MAX_SLOTS = 10000


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.rows = []
        self.cell = None
        self.seen = False
        self.finished = False

    def handle_starttag(self, tag, attrs):
        parent = self.stack[-1] if self.stack else None
        if tag == 'br':
            if self.cell is None: raise ValueError('break outside cell')
            self.cell['parts'].append('\n')
            return
        if tag == 'html':
            valid = parent is None and not self.seen
        elif tag == 'body':
            valid = parent in {None, 'html'} and not self.seen
        elif tag == 'table':
            valid = parent in {None, 'html', 'body'} and not self.seen
            self.seen = True
        elif tag in {'thead', 'tbody', 'tfoot'}:
            valid = parent == 'table'
        elif tag == 'tr':
            valid = parent in {'table', 'thead', 'tbody', 'tfoot'}
            self.rows.append([])
            if len(self.rows) > 1000: raise ValueError('row limit')
        elif tag in {'td', 'th'}:
            valid = parent == 'tr'
            spans = {'rowspan': 1, 'colspan': 1}
            seen_attrs = set()
            for key, value in attrs:
                if key not in spans: continue  # No HTML attribute is copied to the IR.
                if key in seen_attrs or not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,4}', value):
                    raise ValueError('invalid span')
                seen_attrs.add(key)
                spans[key] = int(value)
                if not 1 <= spans[key] <= 1000: raise ValueError('span limit')
            self.cell = {'parts': [], 'row_span': spans['rowspan'], 'col_span': spans['colspan'], 'column_header': tag == 'th'}
        elif tag in {'b', 'strong', 'i', 'em', 'u', 's', 'span', 'p', 'div'}:
            valid = self.cell is not None
            if tag in {'p', 'div'} and self.cell['parts']: self.cell['parts'].append('\n')
        else:
            # Nested tables, executable markup, images, and notation that loses
            # meaning when flattened (sup/sub/math/code) retain the original crop.
            raise ValueError('unsupported table content')
        if not valid or self.finished and tag not in {'html', 'body'}: raise ValueError('invalid nesting')
        self.stack.append(tag)
        if len(self.stack) > 32: raise ValueError('nesting limit')

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag: raise ValueError('unbalanced HTML')
        self.stack.pop()
        if tag in {'td', 'th'}:
            self.cell['text'] = ''.join(self.cell.pop('parts')).strip()
            self.rows[-1].append(self.cell)
            self.cell = None
        elif tag in {'p', 'div'} and self.cell is not None:
            self.cell['parts'].append('\n')
        elif tag == 'table':
            self.finished = True

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != 'br': self.handle_endtag(tag)

    def handle_data(self, text):
        if self.cell is not None: self.cell['parts'].append(text)
        elif text.strip(): raise ValueError('text outside cell')

    def handle_decl(self, decl):
        raise ValueError('declaration not supported')

    def unknown_decl(self, data):
        raise ValueError('declaration not supported')

    def handle_pi(self, data):
        raise ValueError('processing instruction not supported')

    def grid(self):
        if self.stack or not self.finished or not self.rows: raise ValueError('incomplete table')
        occupied, cells, columns = set(), [], 0
        for row, entries in enumerate(self.rows):
            col = 0
            for entry in entries:
                while (row, col) in occupied: col += 1
                end_row, end_col = row + entry['row_span'], col + entry['col_span']
                if end_row > len(self.rows) or end_col > 1000 or entry['row_span'] * entry['col_span'] > MAX_SLOTS:
                    raise ValueError('span outside grid')
                slots = {(r, c) for r in range(row, end_row) for c in range(col, end_col)}
                if occupied & slots or len(occupied) + len(slots) > MAX_SLOTS: raise ValueError('overlap or grid limit')
                occupied.update(slots)
                cells.append(entry | {'start_row_offset_idx': row, 'end_row_offset_idx': end_row,
                    'start_col_offset_idx': col, 'end_col_offset_idx': end_col})
                col = end_col
                columns = max(columns, end_col)
        if not columns or len(occupied) != len(self.rows) * columns: raise ValueError('grid gaps')
        return {'num_rows': len(self.rows), 'num_cols': columns, 'table_cells': cells}


def parse_table_html(value):
    """Return a complete grid, or None for a whole-table image fallback."""
    if not isinstance(value, str) or len(value) > 1_000_000: return None
    parser = _TableParser()
    try:
        parser.feed(value)
        parser.close()
        return parser.grid()
    except ValueError:
        return None
