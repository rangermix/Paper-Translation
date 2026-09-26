"""Conservative candidate rules. A candidate is not a verified technical concept."""
from collections import Counter, defaultdict
import re

from packages.ir import digest
from packages.glossaries import term_matches

VERSION = 'source-terms-v1'
STOP = set('a an the and or of to in on for with by from as is are be we our this that these those each it its into using use used has have not'.split())
DEFINITION = re.compile(r'\b(?:we\s+(?:define|call)\s+(.{1,100}?)\s+(?:as|the)|(.{1,100}?)\s+(?:is defined as|refers to|denotes|means))\b', re.I)
ACRONYM = re.compile(r'([A-Za-z][A-Za-z -]{3,120})\s*\(([A-Z][A-Za-z0-9-]{1,12})\)')


def scope_map(blocks):
    by = {b['id']: b for b in blocks}
    result = {}
    for block in blocks:
        parent, seen = block.get('parent_id'), set()
        while parent in by and parent not in seen:
            seen.add(parent)
            if by[parent]['kind'] == 'heading':
                break
            parent = by[parent].get('parent_id')
        result[block['id']] = parent if parent in by and by[parent]['kind'] == 'heading' else None
    return result


def extract(blocks, evidence, scopes, max_concepts=48, *, stats=None):
    candidates = {}
    evidence_by_block = defaultdict(list)
    for item in evidence:
        evidence_by_block[item['block_id']].append(item)

    def add(term, scope, method, evidence_ids=(), aliases=(), score=0):
        term = re.sub(r'^(?:the|a|an)\s+', '', term.strip(' \t\n.,;:"“”'), flags=re.I)
        if not term or len(term) > 120 or term.casefold() in STOP:
            return
        # Two definitions can describe different senses even in one section.
        key = (term.casefold(), scope, tuple(evidence_ids) if method == 'definition' else ())
        current = candidates.setdefault(key, {'source': term, 'scope': scope, 'aliases': [],
            'evidence_ids': [], 'method': method, 'score': score})
        current['aliases'] = list(dict.fromkeys([*current['aliases'], *aliases]))
        current['evidence_ids'] = list(dict.fromkeys([*current['evidence_ids'], *evidence_ids]))
        current['score'] = max(current['score'], score)

    for block in blocks:
        text = block['normalized_text']
        for sentence in re.split(r'(?<=[.!?。！？])\s*', text):
            match = DEFINITION.search(sentence)
            if match:
                quote_ids = [e['id'] for e in evidence_by_block[block['id']] if sentence.strip() in e['quote'] or e['quote'] in sentence]
                if quote_ids:
                    add(match[1] or match[2], scopes[block['id']], 'definition', quote_ids, score=100)
            for match in ACRONYM.finditer(sentence):
                words = match[1].split()
                acronym = match[2]
                # Match the shortest preceding suffix with the right initials.
                expansion = next((' '.join(words[-n:]) for n in range(2, min(len(words), 12) + 1)
                    if ''.join(w[0] for w in words[-n:] if w.casefold() not in {'of', 'the', 'and'}).casefold() == acronym.casefold()), None)
                if expansion:
                    ids = [e['id'] for e in evidence_by_block[block['id']] if match[0] in e['quote']]
                    if ids:
                        add(expansion, scopes[block['id']], 'acronym', ids, [acronym], 90)

    # Repeated multiword phrases are suggestions only. English word rules do not
    # gate other languages: their headings/definitions remain source evidence.
    counts, spellings, locations = Counter(), {}, defaultdict(set)
    for block in blocks:
        for sentence in re.split(r'[.!?。！？;:\n]', block['normalized_text']):
            matches = list(re.finditer(r"[A-Za-z][A-Za-z-]{1,35}", sentence))
            words = [m[0] for m in matches]
            for width in (2, 3):
                for start in range(len(words) - width + 1):
                    phrase = words[start:start + width]
                    if any(w.casefold() in STOP for w in phrase):
                        continue
                    spans = matches[start:start + width]
                    if any(not sentence[a.end():b.start()].isspace() for a, b in zip(spans, spans[1:])):
                        continue
                    spelling = sentence[spans[0].start():spans[-1].end()]
                    key = spelling.casefold()
                    counts[key] += 1
                    spellings.setdefault(key, spelling)
                    locations[key].add(block['id'])
    existing = {key[0] for key in candidates}
    for key, count in counts.items():
        if count >= 2 and key not in existing:
            ids = [e['id'] for bid in sorted(locations[key]) for e in evidence_by_block[bid]
                   if term_matches(e['quote'], {'source': spellings[key]})]
            if ids:
                add(spellings[key], None, 'frequency', ids[:3], score=min(count, 40))

    # A unique author definition can inform the whole paper. Multiple definitions
    # of the same spelling stay scoped; never merge them by spelling alone.
    senses = Counter(c['source'].casefold() for c in candidates.values() if c['method'] != 'frequency')
    forms = Counter(form.casefold() for c in candidates.values() if c['method'] != 'frequency'
                    for form in {c['source'], *c['aliases']})
    output = []
    ranked = sorted(candidates.values(), key=lambda c: (-c['score'], c['source'].casefold(), c['scope'] or '', c['evidence_ids']))
    if stats is not None:
        stats['omitted_concepts'] = max(0, len(ranked) - max_concepts)
    for candidate in ranked[:max_concepts]:
        if (candidate['method'] != 'frequency' and senses[candidate['source'].casefold()] == 1
                and all(forms[form.casefold()] == 1 for form in [candidate['source'], *candidate['aliases']])):
            candidate['scope'] = None
        candidate['occurrences'] = [b['id'] for b in blocks
            if (candidate['scope'] is None or scopes[b['id']] == candidate['scope'])
            and any(term_matches(b['normalized_text'], {'source': form}) for form in [candidate['source'], *candidate['aliases']])]
        candidate['id'] = 'concept-' + digest({k: candidate[k] for k in ('source', 'scope', 'evidence_ids')})[:20]
        output.append(candidate)
    return sorted(output, key=lambda c: (-c['score'], c['source'].casefold(), c['scope'] or ''))[:max_concepts]
