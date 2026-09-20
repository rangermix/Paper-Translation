"""Render-only links for unambiguous same-page superscript footnote markers."""
from collections import defaultdict
import re

SUPERSCRIPTS = '⁰¹²³⁴⁵⁶⁷⁸⁹'
TO_DIGITS = str.maketrans(SUPERSCRIPTS, '0123456789')
LABEL = re.compile(r'^\s*([0-9]{1,3}|[' + SUPERSCRIPTS + r']{1,3}|[*†‡§¶])(?:[.)]?\s+)')
MARKER = re.compile(r'(?:(?<=[^\W\d_][^\W\d_])|(?<=[.)。]))([' + SUPERSCRIPTS + r']{1,3}|[*†‡§¶])(?=$|[\s.,;:!?)，。])')


class FootnoteIndex:
    def __init__(self, blocks, retained):
        labels = defaultdict(list)
        for block in blocks:
            label = LABEL.match(block['normalized_text']) if block['kind'] == 'footnote' else None
            pages = {loc['page'] for loc in block['provenance']}
            if label and len(pages) == 1:
                labels[next(iter(pages)), label[1].translate(TO_DIGITS)].append(block['id'])
        self.markers = {}
        for block in blocks:
            if block['kind'] not in {'paragraph', 'heading', 'list_item', 'caption', 'table_cell'} or block['id'] in retained:
                continue
            pages = {loc['page'] for loc in block['provenance']}
            if len(pages) != 1:
                continue
            for node in block['source_inline']:
                if node['type'] != 'text' or 'code' in node.get('marks', []):
                    continue
                for match in MARKER.finditer(node['text']):
                    targets = labels.get((next(iter(pages)), match[1].translate(TO_DIGITS)), [])
                    if len(targets) == 1:
                        self.markers.setdefault(block['id'], {})[match[1]] = targets[0]

    def annotate(self, nodes, bid):
        markers = self.markers.get(bid)
        if not markers:
            return nodes
        output = []
        for node in nodes:
            if node['type'] != 'text' or 'code' in node.get('marks', []):
                output.append(node)
                continue
            offset = 0
            for match in MARKER.finditer(node['text']):
                if match[1] not in markers:
                    continue
                if offset < match.start():
                    output.append({**node, 'text': node['text'][offset:match.start()]})
                output.append({'type': 'xref', 'label': match[1], 'target_block_id': markers[match[1]]})
                offset = match.end()
            if offset < len(node['text']):
                output.append({**node, 'text': node['text'][offset:]})
        return output
