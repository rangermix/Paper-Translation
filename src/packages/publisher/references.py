"""Conservative, render-only links into the document's own bibliography."""
from collections import defaultdict
from bisect import bisect_right
import re

from packages.parsers.inline import tokens

YEAR = re.compile(r'\b(?:19|20)\d{2}[a-z]?\b')
NUMBER = re.compile(r'^\s*(?:\[(\d+[a-z]?)\]|(\d+[a-z]?)[.)])\s*')


def author_names(prefix):
    """Accept a complete author list before the date, never a title or venue."""
    prefix = re.sub(r'\s+et al\.?$', '', prefix)
    fields = [field.strip() for field in re.split(r',\s*(?:and\s+|&\s*)?|\s+(?:and|&)\s+', prefix)]

    def surname(field):
        words = field.split()
        if not 1 <= len(words) <= 5:
            return None
        for word in words:
            if word in {'de', 'van', 'von'} or re.fullmatch(r'[A-Z]\.', word):
                continue
            if not word[0].isupper() or not all(c.isalpha() or c in "-'’" for c in word):
                return None
        last = words[-1]
        return last.casefold() if len(last) > 1 and not last.endswith('.') else None

    # "Smith, J. Q., Jones, A." uses surname/initial pairs.
    if len(fields) % 2 == 0 and all(re.fullmatch(r'(?:[A-Z]\.?(?:\s+|$))+', field)
            for field in fields[1::2]):
        names = [surname(field) for field in fields[::2]]
    else:
        # "Jane Q. Smith, Alice Jones". A period after a full word inside
        # this prefix signals a title/venue, so the whole identity is rejected.
        names = [surname(field) for field in fields]
    return names if names and all(names) else []


class ReferenceIndex:
    def __init__(self, blocks, retained):
        self.ids = {bid for bid, reason in retained.items() if reason == 'original_reference'}
        self.numeric = defaultdict(list)
        self.authors = defaultdict(list)
        self.cache = {}
        for block in blocks:
            if block['id'] not in self.ids:
                continue
            text = block['normalized_text'].strip()
            number = NUMBER.match(text)
            if number:
                self.numeric[number[1] or number[2]].append(block['id'])
                text = text[number.end():]
            years = list(YEAR.finditer(text))
            # Multiple distinct dates may belong to the title, publication or
            # access history. Leave that identity unresolved rather than guess.
            if len({year[0] for year in years}) == 1:
                year = years[0]
                tail = text[year.end():].lstrip()
                if tail and tail[0] not in '.,;:)':
                    continue
                prefix = text[:year.start()].strip(' .(')
                authors = author_names(prefix)
                if authors:
                    self.authors[authors[0], year[0]].append((block['id'], set(authors)))

    def resolve(self, label):
        if label not in self.cache:
            self.cache[label] = self._resolve(label)
        return self.cache[label]

    def _resolve(self, label):
        text = label.strip()
        targets = []
        if text.startswith('[') and text.endswith(']'):
            for part in re.split(r'[,;]', text[1:-1]):
                span = re.fullmatch(r'\s*(\d+)(?:\s*[-–—]\s*(\d+))\s*', part)
                if span:
                    if len(span[1]) > 9 or len(span[2]) > 9:
                        return []
                    start, end = int(span[1]), int(span[2])
                    if start > end or end - start >= len(self.numeric):
                        return []
                    labels = [str(number) for number in range(start, end + 1)]
                else:
                    labels = [part.strip()]
                for number in labels:
                    matches = self.numeric.get(number, [])
                    if len(matches) != 1:
                        return []
                    targets.extend(matches)
        else:
            author = None
            for part in text.strip('()').split(';'):
                years = list(YEAR.finditer(part))
                if len(years) != 1:
                    return []
                year = years[0]
                names = part[:year.start()].strip(' ,(')
                if names:
                    author = names
                if not author:
                    return []
                names = re.split(r'\s*(?:&|\band\b)\s*', re.sub(r'\s+et al\.$', '', author))
                candidates = self.authors.get((names[0].casefold(), year[0]), [])
                matches = [bid for bid, authors in candidates if all(name.casefold() in authors for name in names[1:])]
                if len(matches) != 1:
                    return []
                targets.extend(matches)
        return list(dict.fromkeys(targets))

    def matches(self, text):
        for match in tokens(text):
            if match.lastgroup == 'citation':
                targets = self.resolve(match[0])
                if targets:
                    yield match.start(), match.end(), targets

    def segments(self, nodes, atoms):
        """Slice render-only runs, preserving marks and complete protected atoms.

        Older snapshots may store a bracket, number atom and closing bracket as
        separate nodes. Links and math/code are boundaries, never nested links.
        """
        run = []
        for node in nodes:
            if (node['type'] == 'text' and 'code' not in node.get('marks', [])
                    or node['type'] == 'protected_ref' and atoms[node['ref']]['kind'] in {'citation', 'number'}):
                run.append(node)
                continue
            yield from self._segments(run, atoms)
            run = []
            if node['type'] == 'xref' and node['target_block_id'] in self.ids:
                yield [{'type': 'text', 'text': node['label']}], [node['target_block_id']]
            else:
                yield [node], []
        yield from self._segments(run, atoms)

    def _segments(self, nodes, atoms):
        if not nodes:
            return
        offsets, values = [0], []
        for node in nodes:
            value = node['text'] if node['type'] == 'text' else atoms[node['ref']]['value']
            values.append(value)
            offsets.append(offsets[-1] + len(value))
        text = ''.join(values)

        def can_cut(offset):
            index = bisect_right(offsets, offset) - 1
            return offset == offsets[index] or nodes[index]['type'] == 'text'

        def sliced(start, end):
            index = bisect_right(offsets, start) - 1
            parts = []
            while index < len(nodes) and offsets[index] < end:
                node = nodes[index]
                if node['type'] == 'text':
                    node = {**node, 'text': values[index][max(0, start - offsets[index]):end - offsets[index]]}
                parts.append(node)
                index += 1
            return parts

        offset = 0
        for start, end, targets in self.matches(text):
            if not can_cut(start) or not can_cut(end):
                continue
            if start > offset:
                yield sliced(offset, start), []
            yield sliced(start, end), targets
            offset = end
        if offset < len(text):
            yield sliced(offset, len(text)), []
