"""Read-only display names for recorded identities; never consult current settings."""
from functools import lru_cache


@lru_cache(maxsize=1)
def _locked_names():
    from packages.local_models.catalog import artifact, models
    from packages.parsers.catalog import vlm_lock
    from packages.parsers.profiles import PARSER_PROFILES
    names = {}
    for model in models():
        for identifier in (model['id'], artifact(model)['id']):
            names[identifier] = (model['label'], model['revision'])
    parser_labels = {profile['id']: profile['label'] for profile in PARSER_PROFILES}
    for model in vlm_lock()['models']:
        if model['id'] in parser_labels:
            names[model['repo']] = (parser_labels[model['id']], model['revision'])
    return names


def model_identity_view(identity):
    """Add a response-only name when the exact recorded local ID is recognized."""
    if not identity:
        return identity
    result = dict(identity)
    if identity.get('kind') != 'local':
        return result
    match = _locked_names().get(identity.get('model_id'))
    if match and (not identity.get('revision') or identity['revision'] == match[1]):
        result['display_name'] = match[0]
    return result


def model_identity_filter(column, query):
    """Keep recorded-text search; resolve readable labels to exact local identities."""
    from sqlalchemy import Text, and_, cast, or_
    term = query.strip().casefold()
    matches = [and_(column['model_id'].astext == identifier,
                    or_(column['revision'].astext.is_(None), column['revision'].astext == '',
                        column['revision'].astext == revision))
               for identifier, (label, revision) in _locked_names().items()
               if term and term in label.casefold()]
    recorded = cast(column, Text).icontains(query, autoescape=True)
    return or_(recorded, and_(column['kind'].astext == 'local', or_(*matches))) if matches else recorded
