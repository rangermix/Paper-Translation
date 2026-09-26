"""Claude Messages wire conversion only; HTTP, credentials and billing live elsewhere."""
from copy import deepcopy

from packages.ir import canonical_bytes
from .contract import OUTPUT_SCHEMA, REVIEW_SCHEMA, ProviderFailure
from .openai_responses import INSTRUCTIONS, REVIEW_INSTRUCTIONS

ENDPOINT = 'https://api.anthropic.com/v1/messages'
API_VERSION = '2023-06-01'


def request_body(units, profile, glossary, *, review=False):
    if profile.get('provider') != 'anthropic' or profile.get('api_protocol') != 'claude_messages':
        raise ProviderFailure('PROVIDER_CONFIG', 'not_sent')
    if not units:
        raise ProviderFailure('PROVIDER_CONFIG', 'not_sent')
    instructions = REVIEW_INSTRUCTIONS if review else INSTRUCTIONS
    if not review and any(unit.get('repair_reason') for unit in units):
        instructions += ' A previous response failed structural validation. This is the single allowed repair: return every requested ID exactly once, nonempty target text and exactly the original multiset of protected references.'
    from .content import request_content
    content, instructions, output_schema = request_content(units, glossary, review, instructions, REVIEW_SCHEMA if review else OUTPUT_SCHEMA)
    body = {
        'model': profile['model_id'], 'max_tokens': profile['max_output_tokens'],
        'system': instructions,
        'messages': [{'role': 'user', 'content': canonical_bytes(content).decode('utf-8')}],
        'stream': False,
        'output_config': {'format': {'type': 'json_schema', 'schema': deepcopy(output_schema)}},
    }
    # Native Messages has no store flag. No tools/cache control/fallback are
    # requested. Default thinking is model-specific and shares max_tokens.
    if len(canonical_bytes(body)) + 4096 > profile['max_input_tokens']:
        raise ProviderFailure('UNIT_TOO_LARGE', 'not_sent')
    return body


def _count(value):
    return type(value) is int and value >= 0


def _usage(usage):
    if not isinstance(usage, dict):
        return None
    normal = usage.get('input_tokens')
    cached = usage.get('cache_read_input_tokens', 0)
    written = usage.get('cache_creation_input_tokens', 0)
    details = {'cached_tokens': cached if _count(cached) else None, 'cache_write_tokens': written if _count(written) else None}
    result = {
        'input_tokens': normal + cached + written if all(_count(n) for n in (normal, cached, written)) else None,
        'output_tokens': usage.get('output_tokens') if _count(usage.get('output_tokens')) else None,
        'input_tokens_details': details,
    }
    ttl = usage.get('cache_creation')
    if ttl is not None:
        # Copy counters only, never arbitrary strings/envelopes into the ledger.
        if isinstance(ttl, dict):
            counts = {name: ttl.get(name) if _count(ttl.get(name)) else None for name in ('ephemeral_5m_input_tokens', 'ephemeral_1h_input_tokens')}
            details['cache_creation'] = counts
            if not all(_count(n) for n in counts.values()) or sum(counts.values()) != written:
                result['billing_unconfirmed'] = True
        else:
            result['billing_unconfirmed'] = True
    output_details = usage.get('output_tokens_details')
    if output_details is not None:
        thinking = output_details.get('thinking_tokens') if isinstance(output_details, dict) else None
        result['output_tokens_details'] = {'reasoning_tokens': thinking if _count(thinking) else None}
    unpriced = []
    tool_usage = usage.get('server_tool_use')
    if tool_usage is not None:
        if not isinstance(tool_usage, dict) or any(not _count(n) or n != 0 for n in tool_usage.values()):
            unpriced.append('server_tool_use')
        if isinstance(tool_usage, dict):
            result['server_tool_use'] = {name: tool_usage.get(name, 0) if _count(tool_usage.get(name, 0)) else None for name in ('web_fetch_requests', 'web_search_requests')}
    iterations = usage.get('iterations')
    if iterations is not None and iterations != []:
        unpriced.append('iterations')
        result['iterations_count'] = len(iterations) if isinstance(iterations, list) else None
    if unpriced:
        result['unpriced_usage_dimensions'] = unpriced
    return result


def normalize_response(data, http_response):
    result = {
        'request_id': http_response.headers.get('request-id'),
        'response_model': data.get('model') if isinstance(data, dict) else None,
        'usage': _usage(data.get('usage')) if isinstance(data, dict) else None,
        'status': 'unsupported', 'refusal': False, 'output_text': '',
    }
    try:
        if not isinstance(data, dict) or data.get('type') != 'message' or data.get('role') != 'assistant':
            raise ValueError('unsupported message')
        blocks = data['content']
        if not isinstance(blocks, list):
            raise ValueError('unsupported content')
        texts = []
        for block in blocks:
            if not isinstance(block, dict):
                raise ValueError('unsupported block')
            if block.get('type') in ('thinking', 'redacted_thinking'):
                continue
            if block.get('type') != 'text' or not isinstance(block.get('text'), str):
                raise ValueError('unsupported output content')
            texts.append(block['text'])
        stop = data.get('stop_reason')
        stop_details = data.get('stop_details')
        if stop_details is not None and not isinstance(stop_details, dict):
            raise ValueError('unsupported stop details')
        refusal = stop == 'refusal' or isinstance(stop_details, dict) and stop_details.get('type') == 'refusal'
        if refusal:
            result.update(status='completed', refusal=True)
            # Current classifier docs distinguish free pre-output refusals from
            # billed partial refusals; older docs do not. Do not assert a charge.
            if not blocks and isinstance(result['usage'], dict):
                result['usage']['billing_unconfirmed'] = True
        elif stop == 'end_turn':
            result['status'] = 'completed'
        elif stop in ('max_tokens', 'model_context_window_exceeded'):
            result['status'] = 'incomplete'
        else:
            # No stop sequences or tool loops were requested. Never continue one.
            raise ValueError('unsupported stop reason')
        result['output_text'] = ''.join(texts)
    except (ValueError, KeyError, TypeError, AttributeError):
        # Preserve known usage so the common worker can settle before blocking.
        result.update(status='unsupported', failure_code='PROVIDER_UNSUPPORTED_RESPONSE', output_text='')
    return result
