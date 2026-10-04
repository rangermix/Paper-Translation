"""Render-only footnote links backed by typed notes and explicit superscripts."""
from collections import defaultdict
import re


MARKER = re.compile(r'\d{1,3}|[*∗†‡§¶]')
PREFIX = re.compile(r'^\s*(\d{1,3}(?=\s|[.)]|$)|[*∗†‡§¶])')


def marker_key(value):
    return value.replace('∗', '*')


class FootnoteIndex:
    def __init__(self, source, retained):
        self.blocks = {block['id']: block for block in source['blocks']}
        self.atoms = source['protected_atoms']
        self.retained = retained
        self.markers = defaultdict(list)
        for block in source['blocks']:
            if block['kind'] != 'footnote':
                continue
            match = PREFIX.match(block['normalized_text'])
            # Numeric marks may be printed directly against a note body, but
            # only an explicit superscript proves that boundary (not "3D").
            first = next((n for n in block['source_inline'] if n.get('text','').strip() or n['type']!='text'),{})
            if 'superscript' in first.get('marks',[]):
                value = first.get('text','') if first.get('type')=='text' else self.atoms.get(first.get('ref'),{}).get('value','')
                if re.fullmatch(r'\d{1,3}',value):match=re.match(r'(.+)',value)
            pages = {loc['page'] for loc in block['provenance']}
            if match and len(pages) == 1:
                self.markers[next(iter(pages)), marker_key(match[1])].append(block['id'])
        self.linkable = {}
        for bid,block in self.blocks.items():
            evidence = defaultdict(list)
            for index,node in enumerate(block['source_inline']):
                evidence[self.key(node)].append(self.matches(block,index,node))
            # Ambiguous repeated literal marks must not acquire links in a
            # translation just because another source occurrence is a note.
            self.linkable[bid] = {key:choices[0] for key,choices in evidence.items()
                if choices[0] and all(choice==choices[0] for choice in choices)}

    @staticmethod
    def key(node):
        return node['type'],node.get('ref',node.get('text','')),tuple(node.get('marks',[]))

    def matches(self, block, index, node):
        if (block['kind'] in {'footnote','reference','math','code'}
                or 'superscript' not in node.get('marks',[]) or 'code' in node.get('marks',[])
                or node['type'] not in {'text','protected_ref'}):return []
        pages={loc['page'] for loc in block['provenance']}
        if len(pages)!=1:return []
        if node['type']=='protected_ref' and self.atoms[node['ref']]['kind']!='number':return []
        value=node['text'] if node['type']=='text' else self.atoms[node['ref']]['value']
        if not re.fullmatch(r'[\d,*∗†‡§¶\s]+',value):return []
        matches=[]
        for match in MARKER.finditer(value):
            label=match[0]
            targets=self.markers.get((next(iter(pages)),marker_key(label)),[])
            if len(targets)!=1 or targets[0]==block['id']:continue
            if label.isdigit():
                previous=block['source_inline'][index-1] if index else {}
                if self.retained.get(block['id']) in {'original_author_list','original_affiliation'}:continue
                if previous.get('type')=='protected_ref':continue
                if re.search(r'(?:\d|\b[A-Za-z])\s*$',previous.get('text','')):continue
            matches.append((match.start(),match.end(),label,targets[0]))
        return matches

    def nodes(self, nodes, bid):
        result = []
        for node in nodes:
            matches=self.linkable.get(bid,{}).get(self.key(node),[])
            if not matches:result.append(node);continue
            value = node.get('text') if node['type'] == 'text' else self.atoms[node['ref']]['value']
            cursor = 0
            for start,end,label,target in matches:
                if start > cursor:
                    result.append({'type': 'text', 'text': value[cursor:start], 'marks': node['marks']})
                result.append({'type': 'xref', 'target_block_id': target, 'label': label, 'marks': node['marks']})
                cursor = end
            if cursor < len(value):
                result.append({'type': 'text', 'text': value[cursor:], 'marks': node['marks']})
        return result
