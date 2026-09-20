from copy import deepcopy
import re
from packages.ir import canonical_bytes,digest,flatten_inline
from packages.ir.retention import metadata_literals, original_only_blocks
from packages.billing.price import validate_profile
from .languages import check_language_policy

PLANNER_VERSION='protected-academic-quantities-v5'


def plan_units(source,target_locale,profile,block_ids=None,*,nonblocking=False):
    validate_profile(profile)
    check_language_policy(profile,source,target_locale)
    selected=set(block_ids) if block_ids else None
    all_blocks=source['blocks'];by={b['id']:b for b in all_blocks};atoms=source['protected_atoms'];units=[]
    original_only=original_only_blocks(source)
    names = metadata_literals(source, original_only)
    name_pattern = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(name) for name in names) + r')(?!\w)') if names else None
    limit=profile.get('max_unit_characters',2000)
    if profile.get('api_protocol') == 'local_translation':
        from packages.local_models.catalog import get_model
        model = get_model(profile['model_id'])
        available = min(profile['max_input_tokens'], model['context_size'] - min(profile['max_output_tokens'], 2048))
        limit = min(limit, max(1, (available - 2048) // 4))
    def atom_size(atom):
        return max(len(atom['value']), 32) if profile.get('api_protocol') == 'local_translation' else len(atom['value'])
    for index,block in enumerate(all_blocks):
        if selected is not None and block['id'] not in selected:continue
        if not block['translatable'] or block['id'] in original_only or block['language']==target_locale:continue
        context={'heading':by[block['parent_id']]['normalized_text'] if block['parent_id'] and block['parent_id'] not in original_only else '',
            'previous':all_blocks[index-1]['normalized_text'][-500:] if index and all_blocks[index-1]['id'] not in original_only else '',
            'next':all_blocks[index+1]['normalized_text'][:500] if index+1<len(all_blocks) and all_blocks[index+1]['id'] not in original_only else ''}
        context_hash=digest(context);normalized=[];local_atoms={};restore={}
        for node_index,node in enumerate(block['source_inline']):
            if node['type']=='text':
                offset = 0
                for match in name_pattern.finditer(node['text']) if name_pattern else ():
                    if match.start() > offset:
                        normalized.append({'type': 'text', 'text': node['text'][offset:match.start()]})
                    ref = f'metadata-{node_index}-{match.start()}'
                    while ref in atoms or ref in local_atoms:
                        ref += '-literal'
                    local_atoms[ref] = {'kind': 'variable', 'value': match[0]}
                    restore[ref] = {'type': 'text', 'text': match[0]}
                    normalized.append({'type': 'protected_ref', 'ref': ref})
                    offset = match.end()
                if offset < len(node['text']):
                    normalized.append({'type':'text','text':node['text'][offset:]})
            elif node['type']=='protected_ref':
                normalized.append(deepcopy(node));local_atoms[node['ref']]=deepcopy(atoms[node['ref']])
                from packages.ir.quantities import localize_quantity
                atom = atoms[node['ref']]
                localized = localize_quantity(atom['value'], target_locale) if atom['kind'] == 'number' else None
                if localized:
                    restore[node['ref']] = {'type': 'text', 'text': localized}
            else:
                ref=f'link-{node_index}';value=node.get('text',node.get('label',''))
                normalized.append({'type':'protected_ref','ref':ref});local_atoms[ref]={'kind':'citation','value':value};restore[ref]=deepcopy(node)
        if nonblocking and any(atom_size(atom) > limit for atom in local_atoms.values()):
            # Never split or rewrite an indivisible source atom to satisfy a
            # provider limit. Other blocks proceed; this one retains its source.
            continue
        # Preserve a complete paragraph when its actual UTF-8 source plus
        # marker/instruction allowance fits. The four-byte character bound
        # above otherwise splits ordinary English well below the saved limit.
        block_limit = limit
        if profile.get('api_protocol') == 'local_translation':
            widths = [len(n['text']) if n['type'] == 'text' else atom_size(local_atoms[n['ref']]) for n in normalized]
            byte_width = sum(len(n['text'].encode()) if n['type'] == 'text' else
                             max(len(local_atoms[n['ref']]['value'].encode()), 32) for n in normalized)
            if sum(widths) <= profile.get('max_unit_characters', 2000) and byte_width + 2048 <= available:
                block_limit = max(limit, sum(widths))
        batches=[];current=[];size=0
        for node in normalized:
            text=node.get('text') if node['type']=='text' else local_atoms[node['ref']]['value']
            if node['type']=='protected_ref':
                width=atom_size(local_atoms[node['ref']])
                if width>block_limit:raise ValueError('UNIT_TOO_LARGE')
                if current and size+width>block_limit:batches.append(current);current=[];size=0
                current.append(node);size+=width
            else:
                while text:
                    free=block_limit-size
                    if free==0:batches.append(current);current=[];size=0;free=block_limit
                    cut=free
                    if (profile.get('api_protocol') == 'local_translation' and len(text)>free
                            and all(c.isascii() and c.isalnum() for c in (text[free-1],text[free]))):
                        boundaries=list(re.finditer(r'\s+',text[:free]))
                        if boundaries:cut=boundaries[-1].end()
                        elif current:
                            batches.append(current);current=[];size=0
                            continue
                    piece,text=text[:cut],text[cut:];current.append({'type':'text','text':piece});size+=len(piece)
                    if cut<free:
                        batches.append(current);current=[];size=0
        if current:batches.append(current)
        for ordinal,nodes in enumerate(batches):
            refs={n['ref'] for n in nodes if n['type']=='protected_ref'}
            units.append({'unit_id':f'{block["id"]}:{ordinal}','owner_block_id':block['id'],'unit_order':ordinal,'unit_count':len(batches),
                'source_hash':block['source_hash'],'source_language':block['language'],'target_locale':target_locale,'context':context,'context_hash':context_hash,
                'source_inline':nodes,'protected_atoms':{r:local_atoms[r] for r in refs},'restore_nodes':{r:restore[r] for r in refs if r in restore},
                'normalization_version':source['normalization_version'],'planner_version':PLANNER_VERSION})
    if selected and selected-set(by):raise ValueError('UNKNOWN_BLOCK')
    return units


def restore_inline(unit,nodes):return [deepcopy(unit['restore_nodes'].get(n.get('ref'),n)) for n in nodes]


def reassemble(units,results):
    output={}
    for unit in sorted(units,key=lambda u:(u['owner_block_id'],u['unit_order'])):
        if unit['unit_id'] not in results:raise ValueError('UNIT_MISSING')
        output.setdefault(unit['owner_block_id'],[]).extend(restore_inline(unit,results[unit['unit_id']]))
    return output


def cache_shape(unit):
    refs=list(dict.fromkeys(n['ref'] for n in unit['source_inline'] if n['type']=='protected_ref'))
    mapping={ref:'a'+str(index) for index,ref in enumerate(refs)}
    nodes=[{'type':'protected_ref','ref':mapping[n['ref']]} if n['type']=='protected_ref' else n for n in unit['source_inline']]
    return {'source_inline':nodes,'protected_atoms':{mapping[r]:unit['protected_atoms'][r] for r in refs}},mapping


def cache_key(unit,profile,glossary_revision):
    normalized,_=cache_shape(unit)
    protocol={}
    if profile.get('api_protocol') == 'local_translation':
        from packages.providers.local_translation import REQUEST_FORMAT_VERSION
        protocol={'request_format_version':REQUEST_FORMAT_VERSION}
    return digest({'unit':normalized,'context_hash':unit['context_hash'],'locale':unit['target_locale'],'source_language':unit['source_language'],
        'profile':profile,'glossary_revision':glossary_revision,'normalization_version':unit['normalization_version'],'planner_version':PLANNER_VERSION,**protocol})


def cache_encode(unit,nodes):
    _,mapping=cache_shape(unit)
    return [{'type':'protected_ref','ref':mapping[n['ref']]} if n['type']=='protected_ref' else deepcopy(n) for n in nodes]


def cache_decode(unit,nodes):
    _,mapping=cache_shape(unit);inverse={v:k for k,v in mapping.items()}
    return [{'type':'protected_ref','ref':inverse[n['ref']]} if n['type']=='protected_ref' else deepcopy(n) for n in nodes]
