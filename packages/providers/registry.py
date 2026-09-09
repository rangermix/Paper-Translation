"""Protocol identity and headers are configuration, never inferred from a URL."""
from datetime import date

PROTOCOLS = {
    'responses': {'provider': 'openai', 'auth_mode': 'bearer', 'endpoint': 'https://api.openai.com/v1/responses'},
    'chat_completions': {'provider': 'openai', 'auth_mode': 'bearer', 'endpoint': 'https://api.openai.com/v1/chat/completions'},
    'gemini_interactions': {'provider': 'gemini', 'auth_mode': 'api_key', 'endpoint': 'https://generativelanguage.googleapis.com/v1beta/interactions'},
    'claude_messages': {'provider': 'anthropic', 'auth_mode': 'api_key', 'endpoint': 'https://api.anthropic.com/v1/messages'},
}
CLAUDE_API_VERSION = '2023-06-01'


def protocol_definition(protocol):
    if not isinstance(protocol, str) or protocol not in PROTOCOLS:
        raise ValueError('PROVIDER_PROTOCOL')
    return PROTOCOLS[protocol]


def validate_protocol_profile(profile):
    protocol = profile.get('api_protocol', 'responses')
    definition = protocol_definition(protocol)
    if profile.get('provider') != definition['provider']:
        raise ValueError('PROVIDER_PROTOCOL_MISMATCH')
    if profile.get('auth_mode', definition['auth_mode']) not in (definition['auth_mode'], 'none'):
        raise ValueError('PROVIDER_AUTH_MODE')
    if 'api_version' in profile:
        version = profile['api_version']
        if protocol != 'claude_messages' or not isinstance(version, str) or len(version) != 10:
            raise ValueError('PROVIDER_API_VERSION')
        try:
            if date.fromisoformat(version).isoformat() != version:
                raise ValueError('invalid date')
        except ValueError:
            raise ValueError('PROVIDER_API_VERSION') from None
    return definition


def request_body(units, profile, glossary, *, review=False):
    protocol = profile.get('api_protocol', 'responses')
    protocol_definition(protocol)
    if protocol == 'gemini_interactions':
        from .gemini_interactions import request_body as build
    elif protocol == 'claude_messages':
        from .claude_messages import request_body as build
    else:
        from .openai_responses import request_body as build
    return build(units, profile, glossary, review=review)


def privacy_notice(profile):
    if profile.get('api_protocol') == 'claude_messages':
        return 'Only confirmed text and bounded context are sent. Claude Messages has no store=false switch; retention follows the configured service policy. Prompt cache creation is not requested.'
    return 'Only confirmed text and bounded context are sent. Requests use store=false; this does not assert zero provider retention.'
