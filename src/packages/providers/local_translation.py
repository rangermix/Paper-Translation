"""Native translation prompts, one unit per request, no model-generated JSON."""
import re
import time

import httpx

from packages.ir import canonical_bytes, digest, strict_loads
from packages.local_models.catalog import ENDPOINT, get_model
from .contract import ProviderFailure, normalize_request_id

LANGUAGES = dict(zip(
    'ar az bg bn ca cs da de el en es fa fi fr he hi hr hu id it ja kk km ko lo ms my no nl pl pt ro ru sk sl sv ta th tl tr ur uz vi yue'.split(),
    ['Arabic', 'Azerbaijani', 'Bulgarian', 'Bengali', 'Catalan', 'Czech', 'Danish', 'German', 'Greek', 'English',
     'Spanish', 'Persian', 'Finnish', 'French', 'Hebrew', 'Hindi', 'Croatian', 'Hungarian', 'Indonesian', 'Italian',
     'Japanese', 'Kazakh', 'Khmer', 'Korean', 'Lao', 'Malay', 'Burmese', 'Norwegian', 'Dutch', 'Polish', 'Portuguese',
     'Romanian', 'Russian', 'Slovak', 'Slovenian', 'Swedish', 'Tamil', 'Thai', 'Tagalog', 'Turkish', 'Urdu', 'Uzbek', 'Vietnamese', 'Cantonese']))


def language_name(locale):
    if locale in ('und', 'auto'):
        return 'the detected source language'
    if locale in ('zh', 'zh-Hans', 'zh-CN', 'zh-SG'):
        return 'Chinese (Simplified)'
    if locale in ('zh-Hant', 'zh-TW', 'zh-HK', 'zh-MO'):
        return 'Chinese (Traditional)'
    # Keep scripts/regions explicit; language availability is never gated.
    return LANGUAGES.get(locale, locale)


def source_text(unit):
    prefix = '__PT_' + digest(unit)[:16] + '_'
    refs = list(dict.fromkeys(n['ref'] for n in unit['source_inline'] if n['type'] == 'protected_ref'))
    markers = {ref: f'{prefix}{i}__' for i, ref in enumerate(refs)}
    text = ''.join(n['text'] if n['type'] == 'text' else markers[n['ref']] for n in unit['source_inline'])
    return text, {marker: ref for ref, marker in markers.items()}


def request_body(units, profile, glossary, *, review=False):
    if review:
        raise ProviderFailure('LOCAL_MODEL_TRANSLATION_ONLY', 'not_sent')
    if len(units) != 1:
        raise ProviderFailure('LOCAL_MODEL_SINGLE_UNIT', 'not_sent')
    model = get_model(profile['model_id'])
    unit = units[0]
    source, markers = source_text(unit)
    origin, target = language_name(unit['source_language']), language_name(unit['target_locale'])
    prefix = ''
    if markers:
        prefix += 'Keep every __PT_ placeholder unchanged, including repetitions. '
    if glossary:
        prefix += 'Use these translation terms: ' + canonical_bytes(glossary).decode() + '\n'
    context = unit.get('context', {})
    if any(context.values()) and model['family'] == 'hy':
        bounded_context = {key: str(context.get(key, ''))[:100] for key in ('heading', 'previous', 'next')}
        prefix += 'Context for reference only (do not translate it): ' + canonical_bytes(bounded_context).decode() + '\n'
    if model['family'] == 'milmmt':
        prompt = prefix + f'Translate this from {origin} to {target}:\n{origin}: {source}\n{target}:'
        body = {'prompt': prompt, 'add_special_tokens': False}
    else:
        prompt = prefix + f'Translate the following segment into {target}, without additional explanation.\n\n{source}'
        body = {'messages': [{'role': 'user', 'content': prompt}]}
    # UTF-8 byte count bounds token count conservatively; reserve output and template overhead.
    limit = min(profile['max_input_tokens'], model['context_size'] - min(profile['max_output_tokens'], 2048))
    if len(prompt.encode()) + 256 > limit:
        raise ProviderFailure('UNIT_TOO_LARGE', 'not_sent')
    return {**body, 'model': profile['model_id'], 'max_tokens': min(profile['max_output_tokens'], 2048),
            'temperature': 0, 'stream': False}


def target_inline(text, unit):
    _, markers = source_text(unit)
    if not markers:
        return [{'type': 'text', 'text': text}]
    parts = re.split('(' + '|'.join(re.escape(m) for m in markers) + ')', text)
    return [{'type': 'protected_ref', 'ref': markers[p]} if p in markers else {'type': 'text', 'text': p}
            for p in parts if p]


class LocalTranslation:
    def __init__(self, *, transport=None, timeout=300):
        self.transport, self.timeout = transport, timeout

    def prepare(self, profile, check_current=lambda: None):
        """No document content: complete download before obtaining a dispatch permit."""
        base = ENDPOINT.rsplit('/v1/', 1)[0]
        model = get_model(profile['model_id'])
        with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
            try:
                check_current()
                response = client.post(base + '/models/' + model['id'] + '/prepare')
                response.raise_for_status()
                until = time.monotonic() + 3600
                while True:
                    check_current()
                    state = response.json()
                    if state['status'] == 'ready':
                        return
                    if state['status'] == 'failed':
                        raise ProviderFailure(state.get('code', 'LOCAL_MODEL_UNAVAILABLE'), 'not_sent')
                    if time.monotonic() >= until:
                        raise ProviderFailure('LOCAL_MODEL_DOWNLOAD_TIMEOUT', 'not_sent')
                    time.sleep(1)
                    response = client.get(base + '/models/' + model['id'])
                    response.raise_for_status()
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                if isinstance(exc, ProviderFailure):
                    raise
                raise ProviderFailure('LOCAL_MODEL_UNAVAILABLE', 'not_sent') from None

    def translate(self, units, profile, glossary):
        if profile.get('endpoint') != ENDPOINT or profile.get('auth_mode') != 'none':
            raise ProviderFailure('PROVIDER_CONFIG', 'not_sent')
        body = request_body(units, profile, glossary)
        try:
            with httpx.Client(transport=self.transport or httpx.HTTPTransport(retries=0),
                    timeout=self.timeout, trust_env=False, follow_redirects=False) as client:
                response = client.post(ENDPOINT, json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise ProviderFailure('PROVIDER_CONNECT', 'not_sent') from None
        except httpx.HTTPError:
            raise ProviderFailure('OUTCOME_UNKNOWN', 'unknown') from None
        if response.status_code in (400, 404, 409, 422, 503):
            raise ProviderFailure('LOCAL_MODEL_UNAVAILABLE', 'not_sent', http_status=response.status_code)
        if response.status_code != 200:
            raise ProviderFailure('OUTCOME_UNKNOWN', 'unknown')
        try:
            data = strict_loads(response.content)
            result = {'response_model': data.get('model'), 'request_id': normalize_request_id(data.get('id')),
                      'status': 'unsupported', 'refusal': False, 'output_text': '',
                      'usage': {'input_tokens': (data.get('usage') or {}).get('prompt_tokens'),
                                'output_tokens': (data.get('usage') or {}).get('completion_tokens')}}
            if data.get('model') != profile['model_id']:
                return {**result, 'failure_code': 'PROVIDER_MODEL_MISMATCH'}
            if len(data['choices']) != 1:
                return result
            choice = data['choices'][0]
            text = choice.get('text')
            if not isinstance(text, str):
                return result
            result['status'] = 'completed' if choice['finish_reason'] == 'stop' else 'incomplete'
            result['output_text'] = canonical_bytes({'results': [{'unit_id': units[0]['unit_id'],
                'target_inline': target_inline(text, units[0])}]}).decode()
            return result
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ProviderFailure('OUTCOME_UNKNOWN', 'unknown') from None

    def review(self, *args):
        raise ProviderFailure('LOCAL_MODEL_TRANSLATION_ONLY', 'not_sent')
