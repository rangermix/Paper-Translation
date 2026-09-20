"""Conservative, render-only links into the document's own bibliography."""
from collections import defaultdict
from bisect import bisect_right
import re

from packages.parsers.inline import tokens

YEAR = re.compile(r'\b(?:19|20)\d{2}[a-z]?\b')
NUMBER = re.compile(r'^\s*(?:\[(\d+[a-z]?)\]|(\d+[a-z]?)[.)])\s*')


def first_author(text):
    # Support both "Smith, J." and "Jane Q. Smith, ...". Stop before the
    # title, but keep initials. Unrecognized bibliography styles stay unlinked.
    first = re.split(r',|\s+(?:and|&|et al\.)\s*', text, maxsplit=1)[0]
    first = re.split(r'(?<!\b[A-Z])\.\s', first, maxsplit=1)[0].strip(' .(')
    words = first.split()
    if not words or len(words) > 6:
        return None
    surname = words[-1].rstrip('.')
    if not surname or not surname[0].isupper() or not all(c.isalpha() or c in "-'’" for c in surname):
        return None
    return surname.casefold()


def author_names(prefix):
    """Read only the author sentence, never search the paper title for names."""
    authors = re.split(r'(?<!\b[A-Z])\.\s', prefix, maxsplit=1)[0]
    fields = [field.strip(' .') for field in re.split(r',|\s+(?:and|&)\s+', authors)]
    primary = first_author(prefix)
    names = {primary} if primary else set()
    if len(fields[0].split()) > 1:
        # Given-name-first author lists: each field must look like a name.
        for field in fields:
            words = field.split()
            if 2 <= len(words) <= 5 and all(word[0].isupper() or word in {'de', 'van', 'von'} for word in words):
                candidate = first_author(field)
                if candidate:
                    names.add(candidate)
    elif len(fields) % 2 == 0:
        # Surname, initials pairs; a title after an initial is not an author.
        for surname, initials in zip(fields[::2], fields[1::2]):
            if re.fullmatch(r'(?:[A-Z]\.?(?:\s+|$))+', initials):
                candidate = first_author(surname)
                if candidate:
                    names.add(candidate)
    return names


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
                author = first_author(prefix)
                if author:
                    self.authors[author, year[0]].append((block['id'], author_names(prefix)))

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
