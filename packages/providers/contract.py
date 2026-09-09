from collections import Counter
from packages.ir import strict_loads


class ProviderFailure(ValueError):
    def __init__(self,code,outcome='executed_invalid',retry_after=0,*,http_status=None):
        self.code,self.outcome,self.retry_after=code,outcome,retry_after
        self.http_status=http_status
        super().__init__(code)


OUTPUT_SCHEMA={'type':'object','additionalProperties':False,'required':['results'],'properties':{'results':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['unit_id','target_inline'],'properties':{'unit_id':{'type':'string'},'target_inline':{'type':'array','items':{'anyOf':[{'type':'object','additionalProperties':False,'required':['type','text'],'properties':{'type':{'type':'string','enum':['text']},'text':{'type':'string'}}},{'type':'object','additionalProperties':False,'required':['type','ref'],'properties':{'type':{'type':'string','enum':['protected_ref']},'ref':{'type':'string'}}}]}}}}}}}

REVIEW_SCHEMA={'type':'object','additionalProperties':False,'required':['issues'],'properties':{'issues':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['unit_id','rule','severity','source_quote','target_quote','explanation'],'properties':{'unit_id':{'type':'string'},'rule':{'type':'string','enum':['omission','negation','quantity','condition','comparison','terminology']},'severity':{'type':'string','enum':['high','warning']},'source_quote':{'type':'string'},'target_quote':{'type':'string'},'explanation':{'type':'string'}}}}}}


def validate_review(value,units):
    import jsonschema
    from packages.ir import flatten_inline
    if isinstance(value,(str,bytes)):
        try:value=strict_loads(value)
        except ValueError as exc:raise ProviderFailure('PROVIDER_INVALID_JSON') from exc
    if list(jsonschema.Draft202012Validator(REVIEW_SCHEMA).iter_errors(value)):raise ProviderFailure('PROVIDER_REVIEW_SCHEMA')
    by={u['unit_id']:u for u in units}
    for issue in value['issues']:
        unit=by.get(issue['unit_id'])
        if not unit:raise ProviderFailure('PROVIDER_REVIEW_UNKNOWN_UNIT')
        if not issue['source_quote'] or issue['source_quote'] not in flatten_inline(unit['source_inline'],unit['protected_atoms']):raise ProviderFailure('PROVIDER_REVIEW_BAD_EVIDENCE')
        if issue['target_quote'] and issue['target_quote'] not in unit['review_target_text']:raise ProviderFailure('PROVIDER_REVIEW_BAD_EVIDENCE')
        if not issue['explanation'].strip():raise ProviderFailure('PROVIDER_REVIEW_BAD_EVIDENCE')
    return value['issues']


def validate_output(value,units,*,nonblocking=False):
    import jsonschema
    if isinstance(value,(str,bytes)):
        try:value=strict_loads(value)
        except ValueError as exc:raise ProviderFailure('PROVIDER_INVALID_JSON') from exc
    if list(jsonschema.Draft202012Validator(OUTPUT_SCHEMA).iter_errors(value)):raise ProviderFailure('PROVIDER_OUTPUT_SCHEMA')
    results={r['unit_id']:r['target_inline'] for r in value['results']}
    if len(results)!=len(value['results']) or set(results)!={u['unit_id'] for u in units}:raise ProviderFailure('PROVIDER_UNIT_BIJECTION')
    for unit in units:
        nodes=results[unit['unit_id']]
        source=Counter(n['ref'] for n in unit['source_inline'] if n['type']=='protected_ref')
        target=Counter(n['ref'] for n in nodes if n['type']=='protected_ref')
        if set(target)-set(source):raise ProviderFailure('PROTECTED_ATOM_UNKNOWN')
        if source!=target and not nonblocking:raise ProviderFailure('PROTECTED_ATOM_MISMATCH')
        text=''.join(n['text'] if n['type']=='text' else unit['protected_atoms'][n['ref']]['value'] for n in nodes)
        if not text.strip():raise ProviderFailure('PROVIDER_EMPTY_TARGET')
    return results
