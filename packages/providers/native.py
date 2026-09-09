"""A single bounded native API HTTP attempt using an immutable key binding."""
from pathlib import Path

import httpx

from packages.ir import strict_loads
from .contract import ProviderFailure
from .registry import CLAUDE_API_VERSION, request_body, validate_protocol_profile
from .settings import validate_endpoint


class NativeProvider:
    def __init__(self, profile, key_file=None, transport=None, *, timeout=180):
        try:
            definition = validate_protocol_profile(profile)
            self.protocol = profile['api_protocol']
            if self.protocol not in ('gemini_interactions', 'claude_messages'):
                raise ValueError('native protocol required')
            self.endpoint = validate_endpoint(profile['endpoint'])
            self.auth_mode = profile.get('auth_mode', definition['auth_mode'])
            self.api_version = profile.get('api_version', CLAUDE_API_VERSION) if self.protocol == 'claude_messages' else None
            # Bind every field affecting wire/auth behavior before the request.
            self.model_id = profile['model_id']
            if not isinstance(self.model_id, str) or not self.model_id.strip():
                raise ValueError('invalid model')
            self.binding = (self.endpoint, self.protocol, self.auth_mode, self.api_version, self.model_id)
            self._headers = {'Content-Type': 'application/json'}
            if self.protocol == 'claude_messages':
                self._headers['anthropic-version'] = self.api_version
            if self.auth_mode == 'api_key':
                path = Path(key_file) if key_file is not None else None
                if path is None or path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
                    raise ValueError('invalid key file')
                key = path.read_text('utf-8').strip()
                if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
                    raise ValueError('invalid key')
                self._headers['x-goog-api-key' if self.protocol == 'gemini_interactions' else 'x-api-key'] = key
        except (ValueError, OSError, TypeError, KeyError):
            raise ProviderFailure('PROVIDER_CONFIG', 'not_sent') from None
        self.transport = transport
        self.timeout = timeout

    def translate(self, units, profile, glossary):
        return self._request(units, profile, glossary, review=False)

    def review(self, units, profile, glossary):
        return self._request(units, profile, glossary, review=True)

    def _request(self, units, profile, glossary, *, review):
        try:
            definition = validate_protocol_profile(profile)
            version = profile.get('api_version', CLAUDE_API_VERSION) if profile.get('api_protocol') == 'claude_messages' else None
            current = (profile.get('endpoint'), profile.get('api_protocol'), profile.get('auth_mode', definition['auth_mode']), version, profile.get('model_id'))
            if current != self.binding:
                raise ValueError('binding changed')
        except (ValueError, KeyError, TypeError):
            raise ProviderFailure('PROVIDER_CONFIG', 'not_sent') from None
        body = request_body(units, profile, glossary, review=review)
        try:
            with httpx.Client(transport=self.transport or httpx.HTTPTransport(retries=0),
                    timeout=httpx.Timeout(self.timeout, connect=15), follow_redirects=False, trust_env=False) as client:
                response = client.post(self.endpoint, json=body, headers=self._headers)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise ProviderFailure('PROVIDER_CONNECT', 'not_sent') from None
        except httpx.HTTPError:
            raise ProviderFailure('OUTCOME_UNKNOWN', 'unknown') from None
        if response.status_code in (400, 401, 403, 404, 413, 422):
            raise ProviderFailure('PROVIDER_CONFIG', 'not_executed', http_status=response.status_code)
        if response.status_code == 429:
            try:
                delay = min(60, max(0, float(response.headers.get('retry-after', '1'))))
            except ValueError:
                delay = 1
            raise ProviderFailure('PROVIDER_RATE_LIMIT', 'not_executed', delay)
        if response.status_code != 200:
            raise ProviderFailure('OUTCOME_UNKNOWN', 'unknown')
        try:
            value = strict_loads(response.content)
            if not isinstance(value, dict):
                raise ValueError('invalid response')
        except (ValueError, RecursionError):
            raise ProviderFailure('OUTCOME_UNKNOWN', 'unknown') from None
        if self.protocol == 'gemini_interactions':
            from .gemini_interactions import normalize_response
        else:
            from .claude_messages import normalize_response
        result = normalize_response(value, response)
        tracking = result.get('request_id')
        # Tracking IDs are optional evidence, not a prerequisite to settle
        # known usage. Match the ledger's 200-character column and reject
        # malformed provider metadata without truncating or inventing an ID.
        if not isinstance(tracking, str) or not 0 < len(tracking) <= 200 or any(not 33 <= ord(c) < 127 for c in tracking):
            result['request_id'] = None
        reported = result.get('response_model')
        # Gemini resource names may include the documented models/ prefix. Do
        # not guess dated aliases or settle another model using this price.
        expected = self.model_id
        if self.protocol == 'gemini_interactions':
            expected = expected.removeprefix('models/')
            reported = reported.removeprefix('models/') if isinstance(reported, str) else reported
        if not reported or reported != expected:
            result.update(status='unsupported', failure_code='PROVIDER_MODEL_MISMATCH', output_text='')
            if isinstance(result.get('usage'), dict):
                result['usage']['billing_unconfirmed'] = True
        return result
