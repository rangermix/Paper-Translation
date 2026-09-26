"""Freeze a paper/locale decision and project only applicable request context."""
from copy import deepcopy

from packages.glossaries import term_matches
from packages.ir import canonical_bytes, digest
from .terms import scope_map

VERSION = 'paper-context-v1'


def translation_context_mode(profile):
    if profile.get('api_protocol') == 'local_translation':
        from packages.local_models.catalog import get_model
        if get_model(profile['model_id'])['family'] == 'milmmt':
            return 'terms_only'
    return 'background_and_terms'


def freeze(collection, locale, glossary_revision, glossary, *, proposals=None, summary=None,
           analysis=None, warnings=None, context_mode='background_and_terms'):
    pack = deepcopy(collection)
    for concept in pack['concepts']:
        concept.update(target=(proposals or {}).get(concept['id']), review_status='not_reviewed',
                       origin='model' if concept['id'] in (proposals or {}) else 'source_extraction')
    pack.update(target_locale=locale, glossary_revision=glossary_revision,
                glossary=deepcopy(glossary), summary=deepcopy(summary or []),
                analysis=deepcopy(analysis), warnings=list(warnings or []), context_version=VERSION,
                translation_context_mode=context_mode,
                collection_revision=collection['revision'])
    pack.pop('revision', None)
    return {**pack, 'revision': digest(pack)}


def select_context(preparation, source, block_id, text, *, max_bytes=3200):
    if type(max_bytes) is not int or max_bytes < 200:
        raise ValueError('CONTEXT_BUDGET')
    scope = scope_map(source['blocks']).get(block_id)
    explicit = [deepcopy(e) for e in preparation['glossary'] if term_matches(text, e)]
    selected = [c for c in preparation['concepts'] if (c['scope'] is None or c['scope'] == scope)
                and any(term_matches(text, {'source': form}) for form in [c['source'], *c['aliases']])]
    entries = list(explicit)
    targets = {}
    for concept in selected:
        for form in [concept['source'], *concept['aliases']]:
            if concept.get('target'):
                targets.setdefault(form.casefold(), set()).add(concept['target'])
    ambiguous = {form for form, choices in targets.items() if len(choices) > 1}
    for concept in selected:
        if not concept.get('target'):
            continue
        for form in [concept['source'], *concept['aliases']]:
            if form.casefold() not in ambiguous and term_matches(text, {'source': form}) and not any(e['source'].casefold() == form.casefold() for e in explicit):
                entry = {'source': form, 'target': concept['target'], 'mode': 'preferred',
                         'concept_id': concept['id'], 'scope': concept['scope'],
                         'evidence_ids': concept['evidence_ids'], 'origin': 'model',
                         'note': 'Model suggestion; verify against source definition.'}
                if entry not in entries:
                    entries.append(entry)
    wanted = {eid for c in selected for eid in c['evidence_ids']}
    excerpts = [e for e in preparation['evidence'] if e['id'] in wanted]
    result = {'revision': preparation['revision'], 'glossary': entries,
              'summary': [], 'evidence': [], 'omitted': len(ambiguous)}
    while len(canonical_bytes(result)) > max_bytes and result['glossary']:
        result['glossary'].pop(); result['omitted'] += 1
    # Whole exact excerpts only: never silently cut a qualification from a quote.
    for excerpt in excerpts:
        candidate = result | {'evidence': [*result['evidence'], {k: excerpt[k] for k in ('id', 'block_id', 'quote', 'role')} ]}
        if len(canonical_bytes(candidate)) <= max_bytes - 32:
            result = candidate
        else:
            result['omitted'] += 1
    for summary in preparation.get('summary', []):
        candidate = result | {'summary': [*result['summary'], summary]}
        if len(canonical_bytes(candidate)) <= max_bytes - 32:
            result = candidate
        else:
            result['omitted'] += 1
    for excerpt in preparation['evidence']:
        if excerpt['role'] not in {'abstract', 'contribution', 'conclusion'} or excerpt['id'] in wanted:
            continue
        candidate = result | {'evidence': [*result['evidence'], {k: excerpt[k] for k in ('id', 'block_id', 'quote', 'role')}]}
        if len(canonical_bytes(candidate)) <= max_bytes - 32:
            result = candidate
        else:
            result['omitted'] += 1
    return result


def apply_to_units(preparation, source, units, profile):
    from packages.providers.contract import ProviderFailure
    from packages.providers.registry import request_body
    from packages.ir import flatten_inline
    for unit in units:
        original_context = deepcopy(unit['context'])
        selected = select_context(preparation, source, unit['owner_block_id'],
                                  flatten_inline(unit['source_inline'], unit['protected_atoms']))
        unit['preparation_revision'] = preparation['revision']
        unit['preparation_context_mode'] = translation_context_mode(profile)
        unit['glossary_entries'] = selected.pop('glossary')
        unit['context'] = {'heading': unit['context'].get('heading', ''), 'paper': selected}
        while True:
            try:
                request_body([unit], profile, unit['glossary_entries'])
                break
            except ProviderFailure as error:
                if error.code != 'UNIT_TOO_LARGE':
                    raise
                optional = [i for i, e in enumerate(selected['evidence']) if e['role'] not in {'definition', 'acronym'}]
                if optional:
                    selected['evidence'].pop(optional[-1])
                elif selected['summary']:
                    selected['summary'].pop()
                elif selected['evidence']:
                    selected['evidence'].pop()
                elif unit['glossary_entries']:
                    unit['glossary_entries'].pop()
                elif unit['context']['heading']:
                    unit['context']['heading'] = ''
                else:
                    # Retain provenance outside the wire payload. Even the
                    # empty paper envelope/instructions are optional overhead.
                    unit['context'] = original_context
                    unit['preparation_context_omitted'] = True
                    unit['preparation_context_mode'] = 'omitted'
                    break
                selected['omitted'] += 1
        unit['context_hash'] = digest({'context': unit['context'], 'glossary': unit['glossary_entries'],
                                      'preparation_revision': unit['preparation_revision'],
                                      'omitted': unit.get('preparation_context_omitted', False)})
    return units
