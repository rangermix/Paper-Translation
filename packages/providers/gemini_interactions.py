"""Stateless Gemini Interactions wire conversion; no HTTP, credentials or SDK.

The current API returns steps/model_output, not legacy outputs/generateContent.
Only final text enters the existing strict target/review validators.
"""
from copy import deepcopy

from packages.ir import canonical_bytes
from .contract import OUTPUT_SCHEMA, REVIEW_SCHEMA, ProviderFailure
from .openai_responses import INSTRUCTIONS, REVIEW_INSTRUCTIONS

ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/interactions'


def request_body(units, profile, glossary, *, review=False):
    if not units or profile.get('provider') != 'gemini' or profile.get('api_protocol') != 'gemini_interactions':
        raise ProviderFailure('PROVIDER_CONFIG', 'not_sent')
    content = {'target_locale': units[0]['target_locale'], 'units': [{
        'unit_id': u['unit_id'], 'source_language': u['source_language'],
        'source_inline': u['source_inline'], 'protected_atoms': u['protected_atoms'],
        'context': u['context'], **({'target_text': u['review_target_text']} if review else {})
    } for u in units], 'glossary': glossary}
    instructions = REVIEW_INSTRUCTIONS if review else INSTRUCTIONS
    if not review and any(u.get('repair_reason') for u in units):
        instructions += ' A previous response failed structural validation. This is the single allowed repair: return every requested ID exactly once, nonempty target text and exactly the original multiset of protected references.'
    body = {'model': profile['model_id'], 'input': canonical_bytes(content).decode(),
        'system_instruction': instructions, 'store': False, 'stream': False, 'background': False,
        'tools': [], 'generation_config': {'max_output_tokens': profile['max_output_tokens'],
            'thinking_summaries': 'none', 'tool_choice': 'none'},
        'response_format': {'type': 'text', 'mime_type': 'application/json',
            'schema': deepcopy(REVIEW_SCHEMA if review else OUTPUT_SCHEMA)}}
    if len(canonical_bytes(body)) + 4096 > profile['max_input_tokens']:
        raise ProviderFailure('UNIT_TOO_LARGE', 'not_sent')
    return body


def _usage(usage):
    if not isinstance(usage, dict):
        return None
    required = ('total_input_tokens', 'total_cached_tokens', 'total_output_tokens',
                'total_thought_tokens', 'total_tool_use_tokens', 'total_tokens')
    if any(type(usage.get(key)) is not int or usage[key] < 0 for key in required):
        return None
    inp, cached, output, thought, tool, total = (usage[key] for key in required)
    # Cached input is a subset; thought tokens are separate from generated
    # response tokens. The documented 7 + 20 + 22 = 49 example fixes this
    # relationship. Tools/media are outside this text-only price contract.
    if cached > inp or tool or total != inp + output + thought:
        return None
    for field in ('input_tokens_by_modality', 'cached_tokens_by_modality',
                  'output_tokens_by_modality', 'tool_use_tokens_by_modality'):
        if field not in usage:
            continue
        values = usage[field]
        if not isinstance(values, list):
            return None
        for item in values:
            if not isinstance(item, dict) or type(item.get('tokens')) is not int or item['tokens'] < 0:
                return None
            if item.get('modality') != 'text' and item['tokens']:
                return None
            if field == 'tool_use_tokens_by_modality' and item['tokens']:
                return None
    if 'grounding_tool_count' in usage:
        counts = usage['grounding_tool_count']
        if not isinstance(counts, list) or any(not isinstance(item, dict)
                or type(item.get('count')) is not int or item['count'] != 0 for item in counts):
            return None
    return {'input_tokens': inp, 'output_tokens': output + thought,
            'input_tokens_details': {'cached_tokens': cached},
            'output_tokens_details': {'reasoning_tokens': thought}}


def normalize_response(data, http_response):
    data = data if isinstance(data, dict) else {}
    result = {'request_id': http_response.headers.get('x-request-id') or data.get('id'),
        'response_model': data.get('model'), 'usage': _usage(data.get('usage')),
        'status': 'unsupported', 'refusal': False, 'output_text': ''}
    try:
        status = data['status']
        if status not in ('completed', 'incomplete', 'failed', 'cancelled') or data.get('errors'):
            raise ValueError('unsupported interaction status')
        steps = data['steps']
        if not isinstance(steps, list):
            raise ValueError('invalid steps')
        texts = []
        for step in steps:
            if step['type'] == 'thought':
                continue
            # No tool/result/user_input is expected in a stateless text request.
            # Never execute actions or turn them into translation content.
            if step['type'] != 'model_output' or not isinstance(step.get('content'), list):
                raise ValueError('unsupported step')
            for node in step['content']:
                if node['type'] != 'text' or not isinstance(node.get('text'), str):
                    raise ValueError('unsupported output content')
                texts.append(node['text'])
        if not texts:
            raise ValueError('missing model text')
        result.update(status='completed' if status == 'completed' else 'incomplete',
                      output_text=''.join(texts))
    except (ValueError, KeyError, TypeError, AttributeError):
        # Known usage survives a bad envelope: settlement precedes refusal of
        # unsupported content. Missing/uncertain usage stays unknown in billing.
        result.update(status='unsupported', failure_code='PROVIDER_UNSUPPORTED_RESPONSE', output_text='')
    return result
