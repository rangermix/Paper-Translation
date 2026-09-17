"""Integer microcurrency accounting. No provider/model or price defaults."""


def cost_control_enabled(profile):
    """An absent flag preserves already-authorized legacy monetary controls."""
    enabled = profile.get('cost_control_enabled', True)
    if type(enabled) is not bool:
        raise ValueError('COST_CONTROL_INVALID')
    return enabled


def validate_price(price):
    required={'revision','currency','input_micro_per_million','cached_input_micro_per_million','output_micro_per_million','output_includes_reasoning','input_bound_rule'}
    if not isinstance(price,dict) or not required<=set(price):raise ValueError('PRICE_SNAPSHOT_REQUIRED')
    if price['currency']!='USD' or price['output_includes_reasoning'] is not True or price['input_bound_rule']!='utf8-byte-ceiling-v1':raise ValueError('PRICE_BOUND_UNSUPPORTED')
    for name in ('input_micro_per_million','cached_input_micro_per_million','output_micro_per_million'):
        if type(price[name]) is not int or price[name]<0:raise ValueError('PRICE_INVALID')
    if not price['revision']:raise ValueError('PRICE_INVALID')
    return price


def validate_profile(profile):
    required={'configured','provider','model_id','profile_revision','prompt_version','privacy_revision','max_input_tokens','max_output_tokens'}
    if not required<=set(profile) or profile['configured'] is not True:raise ValueError('PROVIDER_CONFIG')
    from packages.providers.registry import validate_protocol_profile
    validate_protocol_profile(profile)
    if profile.get('api_protocol') in ('gemini_interactions','claude_messages') and not profile.get('endpoint'):raise ValueError('PROVIDER_ENDPOINT')
    if not isinstance(profile['model_id'],str) or not profile['model_id']:raise ValueError('PROVIDER_MODEL_REQUIRED')
    for key in ('max_input_tokens','max_output_tokens'):
        if type(profile[key]) is not int or not 1<=profile[key]<=1_000_000:raise ValueError('PROVIDER_TOKEN_LIMIT')
    unit_limit = profile.get('max_unit_characters', 2000)
    if type(unit_limit) is not int or not 1<=unit_limit<=10000:raise ValueError('PROVIDER_UNIT_LIMIT')
    if cost_control_enabled(profile): validate_price(profile.get('price'))
    return profile


def ceiling(tokens,rate):return (tokens*rate+999999)//1000000


def reserve_cost(profile):
    validate_profile(profile)
    if not cost_control_enabled(profile): return None
    p=profile['price']
    return ceiling(profile['max_input_tokens'],max(p['input_micro_per_million'],p['cached_input_micro_per_million']))+ceiling(profile['max_output_tokens'],p['output_micro_per_million'])


def actual_cost(price,usage):
    validate_price(price)
    if not isinstance(usage,dict) or not {'input_tokens','output_tokens'}<=set(usage):raise ValueError('USAGE_MISSING')
    if usage.get('billing_unconfirmed'):raise ValueError('USAGE_BILLING_UNCONFIRMED')
    if usage.get('unpriced_usage_dimensions'):raise ValueError('UNPRICED_USAGE_DIMENSION')
    input_details=usage.get('input_tokens_details',{})
    output_details=usage.get('output_tokens_details',{})
    if not isinstance(input_details,dict) or not isinstance(output_details,dict):raise ValueError('USAGE_INVALID')
    inp,out=usage['input_tokens'],usage['output_tokens'];cached=input_details.get('cached_tokens',0)
    if any(type(n) is not int or n<0 for n in (inp,out,cached)) or cached>inp:raise ValueError('USAGE_INVALID')
    reasoning=output_details.get('reasoning_tokens',0)
    if type(reasoning) is not int or not 0<=reasoning<=out:raise ValueError('USAGE_INVALID')
    if input_details.get('cache_write_tokens',0):raise ValueError('UNPRICED_USAGE_DIMENSION')
    weighted=(inp-cached)*price['input_micro_per_million']+cached*price['cached_input_micro_per_million']+out*price['output_micro_per_million']
    return (weighted+999999)//1000000
