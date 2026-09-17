from dataclasses import dataclass
import json
import os
from pathlib import Path


DEFAULT_PROVIDER_LIMITS = {'max_input_tokens': 32768, 'max_output_tokens': 8192, 'max_unit_characters': 2000}


@dataclass(frozen=True)
class Config:
    data: Path
    uploads: Path
    parser_inputs: Path
    parser_outputs: Path
    database_url: str
    allowed_hosts: tuple[str, ...]
    origins: tuple[str, ...]
    phase: str = 'M2'
    max_pdf_bytes: int = 50 * 1024 * 1024
    chunk_bytes: int = 4 * 1024 * 1024
    max_pages: int = 200
    lease_seconds: int = 60

    @classmethod
    def load(cls):
        path = Path(os.environ.get('DATABASE_CONFIG_FILE', '/internal/database.json'))
        database_url = ''
        if path.is_file():
            database_url = json.loads(path.read_text())['url']
        elif os.environ.get('LIBRARY_TEST_MODE') == '1':
            database_url = os.environ.get('TEST_DATABASE_URL', '')
        return cls(
            data=Path(os.environ.get('DATA_DIR', '/data')),
            uploads=Path(os.environ.get('UPLOADS_DIR', '/uploads')),
            parser_inputs=Path(os.environ.get('PARSER_INPUTS_DIR', '/parser_inputs')),
            parser_outputs=Path(os.environ.get('PARSER_OUTPUTS_DIR', '/parser_outputs')),
            database_url=database_url,
            allowed_hosts=tuple(os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1],testserver').split(',')),
            origins=tuple(os.environ.get('APP_ORIGINS', 'http://localhost:8080,http://127.0.0.1:8080,http://testserver').split(',')),
            phase=os.environ.get('LIBRARY_PHASE', 'M2'),
        )


def missing_profile_fields(value):
    """Completeness is separate from accepting strictly typed saved settings."""
    missing = [key for key in ('endpoint', 'model_id', 'max_input_tokens', 'max_output_tokens') if not value.get(key)]
    from packages.billing.price import cost_control_enabled
    if not cost_control_enabled(value):
        return missing
    price = value.get('price', {})
    for key in ('revision', 'currency', 'input_micro_per_million', 'cached_input_micro_per_million',
                'output_micro_per_million', 'output_includes_reasoning', 'input_bound_rule'):
        if key not in price or price[key] is None or (key == 'output_includes_reasoning' and price[key] is not True):
            missing.append('price.' + key)
    return missing


def validate_public_profile(value, *, allow_incomplete=False):
    """Reject nonpublic fields before metadata can be persisted or exposed."""
    from packages.billing.price import validate_profile
    allowed = {'configured', 'provider', 'model_id', 'profile_revision', 'prompt_version', 'privacy_revision',
        'enabled_pairs', 'max_input_tokens', 'max_output_tokens', 'max_unit_characters', 'price', 'semantic_review_enabled',
        'endpoint', 'api_protocol', 'auth_mode', 'api_version', 'config_revision', 'credential_revision', 'cost_control_enabled'}
    price_fields = {'revision', 'currency', 'input_micro_per_million', 'cached_input_micro_per_million',
        'output_micro_per_million', 'output_includes_reasoning', 'input_bound_rule'}
    if not isinstance(value, dict) or set(value) - allowed or not isinstance(value.get('price', {}), dict) or set(value.get('price', {})) - price_fields:
        raise ValueError('PROVIDER_PUBLIC_FIELDS')
    if not isinstance(value.get('enabled_pairs'), list) or not all(isinstance(pair, list) and len(pair) == 2 and
            all(isinstance(lang, str) and 1 <= len(lang) <= 32 for lang in pair) for pair in value['enabled_pairs']):
        raise ValueError('PROVIDER_LANGUAGE_PAIRS')
    for key in ('model_id', 'profile_revision', 'prompt_version', 'privacy_revision'):
        if allow_incomplete and key == 'model_id' and value.get(key) in (None, ''):
            continue
        if not isinstance(value.get(key), str) or not 1 <= len(value[key]) <= 160:
            raise ValueError('PROVIDER_PUBLIC_METADATA')
    if 'semantic_review_enabled' in value and type(value['semantic_review_enabled']) is not bool:
        raise ValueError('PROVIDER_PUBLIC_METADATA')
    from packages.billing.price import cost_control_enabled
    controlled = cost_control_enabled(value)
    public_price = value.get('price', {})
    if ((not allow_incomplete and controlled) or 'revision' in public_price) and (not isinstance(public_price.get('revision'), str) or not 1 <= len(public_price['revision']) <= 160):
        raise ValueError('PROVIDER_PUBLIC_METADATA')
    if 'max_unit_characters' in value and type(value['max_unit_characters']) is not int:
        raise ValueError('PROVIDER_UNIT_LIMIT')
    if 'endpoint' in value and not (allow_incomplete and value['endpoint'] == ''):
        from packages.providers.settings import validate_endpoint
        validate_endpoint(value['endpoint'])
    from packages.providers.registry import validate_protocol_profile
    validate_protocol_profile(value)
    for key in ('config_revision', 'credential_revision'):
        if key in value:
            import re
            if not isinstance(value[key], str) or not re.fullmatch(r'[a-f0-9]{32}', value[key]):
                raise ValueError('PROVIDER_REVISION')
    if allow_incomplete:
        if type(value.get('configured')) is not bool:
            raise ValueError('PROVIDER_CONFIG')
        for key, limit in (('max_input_tokens', 1000000), ('max_output_tokens', 1000000), ('max_unit_characters', 10000)):
            if key in value and (type(value[key]) is not int or not 1 <= value[key] <= limit):
                raise ValueError('PROVIDER_TOKEN_LIMIT')
        price = public_price
        for key in ('input_micro_per_million', 'cached_input_micro_per_million', 'output_micro_per_million'):
            if key in price and (type(price[key]) is not int or not 0 <= price[key] <= 10**15):
                raise ValueError('PRICE_INVALID')
        if ('currency' in price and price['currency'] != 'USD'
                or 'input_bound_rule' in price and price['input_bound_rule'] != 'utf8-byte-ceiling-v1'
                or 'output_includes_reasoning' in price and type(price['output_includes_reasoning']) is not bool):
            raise ValueError('PRICE_BOUND_UNSUPPORTED')
        value = {**value, 'configured': not missing_profile_fields(value)}
        return validate_profile(value) if value['configured'] else value
    return validate_profile(value)


def provider_profile():
    """Public versioned metadata only. The API never reads the Provider secret."""
    disabled = {'configured': False, 'provider': 'openai', 'enabled_pairs': [], 'reason': 'PROVIDER_CONFIG'}
    try:
        from packages.providers.settings import managed_profile
        managed = managed_profile()
        if managed is not None:
            return managed
        return external_provider_profile()
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return disabled


def external_provider_profile():
    """Compatibility profile; never reads or stores the external key."""
    path = Path(os.environ.get('PROVIDER_PROFILE_FILE', '/config/provider.json'))
    disabled = {'configured': False, 'provider': 'openai', 'enabled_pairs': [], 'reason': 'PROVIDER_CONFIG'}
    try:
        from packages.ir import strict_loads
        if path.stat().st_size > 16384:
            return disabled
        return validate_public_profile(strict_loads(path.read_bytes()))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return disabled
