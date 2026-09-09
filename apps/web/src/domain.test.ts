import { describe, expect, it } from 'vitest';
import { inlineText, locatorStyle, replaceTextNodes, codePointOffset, sourceTextEdit, canConfirmPreflight, canResumeJob } from './domain';
describe('editor invariants', () => {
  it('preserves protected atoms when editing text', () => {
    const nodes = [{ type: 'text' as const, text: 'Value ' }, { type: 'protected_ref' as const, id: 'p1' }, { type: 'text' as const, text: '.' }];
    expect(replaceTextNodes(nodes, ['数值 ', '。'])).toEqual([{ type: 'text', text: '数值 ' }, nodes[1], { type: 'text', text: '。' }]);
    expect(inlineText(nodes, { p1: '64' })).toBe('Value 64.');
  });
  it('saves Unicode code point offsets, including non-BMP characters', () => expect(codePointOffset('A😀文', 3)).toBe(2));
  it('isolates the actual mechanical edit without replacing protected neighboring content', () => expect(sourceTextEdit('A😀  64 tokens.', 'A😀 64 tokens.')).toEqual({start: 3, end: 4, text: ''}));
  it('converts normalized top-left PDF points to proportional page bounds', () => {
    expect(locatorStyle({ page: 2, bbox: [25, 20, 75, 80], page_size: [100, 200] })).toEqual({ left: '25%', top: '10%', width: '50%', height: '30%' });
  });
  it('rejects malformed or out-of-page PDF locations', () => expect(() => locatorStyle({ page: 1, bbox: [-1, 0, 20, 30], page_size: [100, 200] })).toThrow());
  it('content findings and absent manual review never block an authorized request', () => {
    expect(canConfirmPreflight({ status: 'OCR_REQUIRED', unresolved_blocks: 1 }, false, true, 100)).toBe(true);
    expect(canConfirmPreflight({ status: 'ready', unresolved_blocks: 297 }, false, false, 100)).toBe(false);
    expect(canConfirmPreflight({ status: 'failed', unresolved_blocks: 0 }, false, true, 100)).toBe(false);
  });
  it('unknown paid outcomes cannot use the ordinary resume action', () => {
    expect(canResumeJob('outcome_unknown')).toBe(false);
    expect(canResumeJob('paused')).toBe(true);
  });
});
