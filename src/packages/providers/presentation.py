"""Response-only names for the exact local model in a confirmed profile."""
from packages.local_models.catalog import get_model


def profile_view(profile):
    """Keep the profile and its digest inputs unchanged; never read current settings."""
    result = dict(profile)
    result.pop('model_display_name', None)
    if profile.get('api_protocol') == 'local_translation' and profile.get('model_id'):
        try:
            model = get_model(profile['model_id'])
        except ValueError:
            pass
        else:
            result['model_display_name'] = model['label']
    return result
