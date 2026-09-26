"""Protocol-independent request data; transport and model templates stay separate."""
from .contract import ProviderFailure


def request_content(units, glossary, review, instructions, schema):
    if any(u.get('operation') == 'preparation' for u in units):
        if review or len(units) != 1:
            raise ProviderFailure('PREPARATION_REQUEST', 'not_sent')
        from packages.preparation.analysis import INSTRUCTIONS, SCHEMA
        return units[0]['content'], INSTRUCTIONS, SCHEMA
    content = {'target_locale': units[0]['target_locale'], 'units': [{
        'unit_id': u['unit_id'], 'source_language': u['source_language'],
        'source_inline': u['source_inline'], 'protected_atoms': u['protected_atoms'],
        'context': u['context'], **({'target_text': u['review_target_text']} if review else {})
    } for u in units], 'glossary': glossary}
    if not review and any(u.get('preparation_revision') and not u.get('preparation_context_omitted') for u in units):
        instructions += ' Use context only to interpret the source unit. Never translate or reproduce background context in the target. Explicit glossary choices take precedence over automatic suggestions.'
    return content, instructions, schema
