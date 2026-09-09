#!/usr/bin/env python3
"""Validate this specification package, NOT the planned application.

Usage: python tools/check_package.py
Requires jsonschema; no network, model keys, database or provider calls.
"""
from __future__ import annotations
import copy, hashlib, json, re, sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse, unquote
import jsonschema

ROOT=Path(__file__).resolve().parents[1]
CSS_HASH='51dacbcd96a21214ed83a62cad870a6281eb20db1aa260f3a7d782c58fdd18a8'
CHECKS=[]
def load(p): return json.loads((ROOT/p).read_text('utf-8'))
def canonical(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def digest(b): return hashlib.sha256(b).hexdigest()
def check(name,fn):
 try:
  fn(); CHECKS.append({'name':name,'result':'pass'})
 except Exception as e:
  CHECKS.append({'name':name,'result':'fail','detail':str(e)})
def must(condition,message):
 if not condition: raise ValueError(message)
def invalid(fn):
 try:fn()
 except (ValueError,jsonschema.ValidationError):return
 raise AssertionError('Expected invalid input to be rejected')

SCHEMA=load('contracts/document-ir-v3.schema.json')
def flatten(items,atoms):
 out=[]
 for x in items:
  k=x['type']
  if k=='text':out.append(x['text'])
  elif k=='protected_ref':
   must(x['ref'] in atoms,'Unknown protected ref');out.append(atoms[x['ref']]['value'])
  elif k=='link':out.append(x['text'])
  elif k=='xref':out.append(x['label'])
 return ''.join(out)
def semantic(v):
 """Bounded reference checks for this contract, not a production security parser."""
 jsonschema.Draft202012Validator(SCHEMA,format_checker=jsonschema.FormatChecker()).validate(v)
 src=v['source_revision'];tr=v['translation_revision'];atoms=src['protected_atoms']
 blocks=src['blocks'];by={b['id']:b for b in blocks};assets={a['id']:a for a in src['assets']}
 must(len(by)==len(blocks),'duplicate block IDs')
 must(len(assets)==len(src['assets']),'duplicate asset IDs')
 must(src['original_asset_id'] in assets,'missing original asset')
 must(assets[src['original_asset_id']]['sha256']==src['sha256'],'source SHA mismatch')
 must(assets[src['original_asset_id']]['media_type']=='application/pdf','original must be PDF')
 roots={b['id'] for b in blocks if b['owner_id'] is None}
 must(set(src['reading_order'])==roots and len(src['reading_order'])==len(roots),'root order mismatch')
 must(src['title_block_id'] in roots and by[src['title_block_id']]['kind']=='heading','invalid title block')
 must(v['document']['title']==by[src['title_block_id']]['normalized_text'],'title drift')
 must(tr['source_revision_id']==src['id'],'source revision mismatch')
 for a in assets.values():
  p=Path(a['storage_key'])
  must(not p.is_absolute() and '..' not in p.parts and '\\' not in a['storage_key'],'unsafe asset path')
 for b in blocks:
  if b['parent_id'] is not None:must(b['parent_id'] in by,'parent missing')
  seen=set();x=b
  while x['parent_id'] is not None:
   must(x['id'] not in seen,'parent cycle');seen.add(x['id']);x=by[x['parent_id']]
  if b['owner_id'] is not None:
   must(b['owner_id'] in by,'owner missing')
   must(b['kind'] in {'caption','table_cell'},'illegal owned block kind')
   must(by[b['owner_id']]['owner_id'] is None,'nested owner unsupported')
  norm=b['raw_text'];edits=b['normalization_edits'];prev=0
  for e in edits:
   must(prev<=e['raw_start']<=e['raw_end']<=len(norm),'invalid normalization ranges');prev=e['raw_end']
  for e in reversed(edits):norm=norm[:e['raw_start']]+e['replacement']+norm[e['raw_end']:]
  must(norm==b['normalized_text'],'normalization is not reproducible')
  must(flatten(b['source_inline'],atoms)==b['normalized_text'],'source inline/text mismatch')
  resolved={x['ref']:atoms[x['ref']] for x in b['source_inline'] if x['type']=='protected_ref'}
  expected=digest(canonical({'kind':b['kind'],'normalized_text':b['normalized_text'],'source_inline':b['source_inline'],'semantic_attributes':b['attributes'],'resolved_protected_atoms':resolved}))
  must(expected==b['source_hash'],'block source hash mismatch')
  for x in b['source_inline']:
   if x['type']=='xref':must(x['target_block_id'] in by,'unknown xref')
  for p in b['provenance']:
   must(p['type']=='pdf' and p['asset_id']==src['original_asset_id'],'PDF provenance must refer to the original')
   key='asset_id';must(p[key] in assets,'provenance asset missing')
   if p['type']=='text':must(p['char_start']<=p['char_end'],'inverted character interval')
   if p['type']=='pdf':
    x1,y1,x2,y2=p['bbox'];w,h=p['page_size'];must(0<=x1<=x2<=w and 0<=y1<=y2<=h,'bbox outside page')
  a=b['attributes']
  if 'asset_id' in a:must(a['asset_id'] in assets,'figure asset missing')
  for cap in a.get('caption_block_ids',[]):must(cap in by and by[cap]['kind']=='caption' and by[cap]['owner_id']==b['id'],'caption owner mismatch')
  if b['kind']=='table' and a['representation']=='structured':
   covered=set();cellids=set()
   for c in a['cells']:
    cid=c['content_block_id'];must(cid in by and by[cid]['kind']=='table_cell' and by[cid]['owner_id']==b['id'],'table owner mismatch')
    must(cid not in cellids,'duplicate cell ref');cellids.add(cid)
    for row in range(c['row'],c['row']+c['row_span']):
     for col in range(c['column'],c['column']+c['column_span']):
      must(row<a['rows'] and col<a['columns'] and (row,col) not in covered,'cell overlap/out of bounds');covered.add((row,col))
   must(len(covered)==a['rows']*a['columns'],'table coverage gap')
  if b['kind']=='caption' and b['owner_id']:
   must(b['id'] in by[b['owner_id']]['attributes'].get('caption_block_ids',[]),'orphan caption')
  if b['kind']=='table_cell' and b['owner_id']:
   must(b['id'] in [c['content_block_id'] for c in by[b['owner_id']]['attributes'].get('cells',[])],'orphan table cell')
 results=tr['results'];byresult={r['block_id']:r for r in results}
 must(len(byresult)==len(results) and set(byresult)==set(by),'result set not bijective')
 for rid,r in byresult.items():
  b=by[rid];must(r['source_hash']==b['source_hash'],'stale target source hash')
  if r['status']=='unresolved':must(v['render']['mode']=='draft','unresolved release')
  if r['status']=='translated':
   must(flatten(r['target_inline'],atoms).strip()!='','empty translated content')
   sa=Counter(x['ref'] for x in b['source_inline'] if x['type']=='protected_ref');ta=Counter(x['ref'] for x in r['target_inline'] if x['type']=='protected_ref')
   must(sa==ta,'protected atom multiplicity mismatch')
   sx=Counter(x['target_block_id'] for x in b['source_inline'] if x['type']=='xref');tx=Counter(x['target_block_id'] for x in r['target_inline'] if x['type']=='xref')
   must(sx==tx,'xref multiplicity mismatch')
   allowedlinks={x['href'] for x in b['source_inline'] if x['type']=='link'}
   for x in r['target_inline']:
    if x['type']=='link':must(x['href'] in allowedlinks,'unapproved model link')
  elif r['status']=='retained':
   must(not r['target_inline'] and bool(r['reason']),'invalid retained result')
   permitted=b['kind'] in {'code','math','figure','reference','table'}
   permitted=permitted or (r['reason']=='same_language' and b['language']==tr['target_language'])
   must(permitted,'required prose cannot be retained')
  if r['review_state']=='human_reviewed':
   rv=r['review_record'];must(rv is not None,'human review lacks record')
   must(rv['source_hash']==b['source_hash'] and rv['target_hash']==digest(canonical(r['target_inline'])) and rv['context_hash']==r['context_hash'],'stale review')
   must(rv['glossary_revision']==r['generation']['glossary_revision'],'review glossary mismatch')
 title_result=byresult[src['title_block_id']]
 title_text=by[src['title_block_id']]['normalized_text'] if title_result['status']=='retained' else flatten(title_result['target_inline'],atoms)
 must(tr['title']==title_text,'target title mismatch')
 return True

