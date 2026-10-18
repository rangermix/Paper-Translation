import { describe, expect, it } from 'vitest';
import type { Inline } from '../types';
import { editInline, inlineValue, reconcileInline } from './inline-editing';

describe('continuous editing preserves the inline contract', () => {
  const nodes: Inline[] = [{ type: 'text', text: 'A ' }, { type: 'text', text: 'bold', marks: ['strong'], output_path: 'cell/0' },
    { type: 'xref', label: ' reference', target_block_id: 'b12' }, { type: 'link', text: ' link', href: 'https://example.org', marks: ['emphasis'] },
    { type: 'protected_ref', ref: 'formula' }, { type: 'text', text: ' tail' }];
  const atoms = { formula: 'x²' };
  it('edits across ordinary nodes while retaining their marks and identities', () => {
    const edited = editInline(nodes, 1, 5, ' longer ', atoms);
    expect(edited[0]).toEqual({ type: 'text', text: 'A longer ' });
    expect(edited[1]).toEqual({ type: 'text', text: 'd', marks: ['strong'], output_path: 'cell/0' });
    expect(edited.slice(2)).toEqual(nodes.slice(2));
    expect(nodes[1]).toHaveProperty('text', 'bold');
  });
  it('retains xref/link fields while their labels change', () => {
    const edited = reconcileInline(nodes, 'A bold new reference linkx² tail', atoms);
    expect(edited[2]).toMatchObject({ type: 'xref', target_block_id: 'b12', label: ' new reference' });
    expect(edited[3]).toEqual(nodes[3]);
  });
  it('rejects deleting, replacing or inserting inside a protected object', () => {
    const offset = nodes.slice(0,4).map(n => inlineValue(n, atoms)).join('').length;
    for (const [start, end] of [[offset, offset + 2], [offset - 1, offset + 1], [offset + 1, offset + 1]]) {
      expect(() => editInline(nodes, start, end, 'new', atoms)).toThrow('受保护');
    }
    expect(editInline(nodes, offset, offset, 'before', atoms)[4]).toEqual(nodes[4]);
    expect(editInline(nodes, offset + 2, offset + 2, 'after', atoms)[4]).toEqual(nodes[4]);
  });
  it('preserves adjacent protected objects and unknown atom labels', () => {
    const protectedNodes: Inline[] = [{ type:'protected_ref',id:'x' }, { type:'protected_ref',ref_id:'y' }];
    expect(editInline(protectedNodes, 3, 3, 'between')).toEqual([protectedNodes[0], { type:'text',text:'between' }, protectedNodes[1]]);
  });
  it('handles empty content, emoji, newlines and literal hostile markup as text', () => {
    expect(editInline([],0,0,'中文')).toEqual([{type:'text',text:'中文'}]);
    expect(reconcileInline([{type:'text',text:'A😀B'}], 'A😁\n<script>B')).toEqual([{type:'text',text:'A😁\n<script>B'}]);
  });
});
