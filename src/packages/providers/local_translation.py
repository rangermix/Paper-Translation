"""Native translation prompts, one unit per request, no model-generated JSON."""
import re
import time

import httpx

from packages.ir import canonical_bytes, strict_loads
from packages.local_models.catalog import ENDPOINT, get_model
from .contract import ProviderFailure, normalize_request_id

REQUEST_FORMAT_VERSION = 'local-translation-v2'

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
    refs = list(dict.fromkeys(n['ref'] for n in unit['source_inline'] if n['type'] == 'protected_ref'))
    literal = ''.join(n['text'] for n in unit['source_inline'] if n['type'] == 'text')
    namespace = 0
    while True:
        prefix = 'PT' if namespace == 0 else f'PT{namespace}_'
        markers = {ref: '{{' + prefix + str(i) + '}}' for i, ref in enumerate(refs)}
        if not any(marker in literal or marker[:-1] in literal for marker in markers.values()):
            break
        namespace += 1
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
    keep_markers = ('Preserve every ' + next(iter(markers)) + '-style variable exactly, including repetitions. ') if markers else ''
    terms = 'Use these translation terms: ' + canonical_bytes(glossary).decode() + '\n' if glossary else ''
    if model['family'] == 'milmmt':
        prompt = keep_markers + terms + f'Translate this from {origin} to {target}:\n{origin}: {source}\n{target}:'
        body = {'prompt': prompt, 'add_special_tokens': False}
    else:
        # Hy-MT2's native background/source sections keep instructions and
        # neighbouring text out of the segment the translation model renders.
        context = unit.get('context', {})
        background = '\n'.join(key.title() + ': ' + str(context[key])[:100]
            for key in ('heading', 'previous', 'next') if context.get(key))
        if terms:
            background = background + '\n' + terms if background else terms
        prefix = '[Background Information]\n' + background + '\n\n' if background else ''
        consideration = ', taking the provided background information into consideration' if background else ''
        prompt = (prefix + f'Please translate the following text into {target}{consideration}. '
            'Output only the translated text, without any additional explanation. ' + keep_markers
            + '\n[Source Text]\n' + source)
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
    # A missing final brace leaves an unambiguous known variable identity.
    # Restore only that exact spelling; unknown IDs remain visible to QA.
    for marker in markers:
        text = re.sub(re.escape(marker[:-1]) + r'(?!\})', lambda _: marker, text)
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
