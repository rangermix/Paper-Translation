import type { Inline } from '../types';

export const inlineValue = (node: Inline, atoms: Record<string, string> = {}) => node.type === 'protected_ref'
  ? atoms[node.ref ?? node.id ?? node.ref_id ?? ''] ?? `[${node.ref ?? node.id ?? node.ref_id ?? '保护内容'}]`
  : node.type === 'xref' ? node.label : node.text;

/** Apply a single text edit without flattening the semantic inline runs. */
export function editInline(nodes: Inline[], start: number, end: number, inserted: string, atoms: Record<string, string> = {}): Inline[] {
  const length = nodes.reduce((sum, node) => sum + inlineValue(node, atoms).length, 0);
  if (start < 0 || end < start || end > length) throw new Error('编辑位置已变化，请重试。');
  let offset = 0;
  for (const node of nodes) {
    const next = offset + inlineValue(node, atoms).length;
    if (node.type === 'protected_ref' && (start < next && end > offset || start === end && start > offset && start < next)) {
      throw new Error('所选范围包含受保护的公式或引用。请在它的两侧分别编辑；原内容已保留。');
    }
    offset = next;
  }
  if (!nodes.length) return [{ type: 'text', text: inserted }];
  offset = 0;
  let applied = false;
  const result: Inline[] = [];
  for (const node of nodes) {
    const value = inlineValue(node, atoms), next = offset + value.length;
    if (node.type === 'protected_ref') {
      if (!applied && start === offset) { result.push({ type: 'text', text: inserted }); applied = true; }
      result.push(node);
    } else {
      const overlaps = start < next && end > offset;
      const insertHere = !applied && start >= offset && start <= next;
      if (overlaps || insertHere) {
        const from = Math.max(0, Math.min(value.length, start - offset));
        const to = Math.max(from, Math.min(value.length, end - offset));
        const text = value.slice(0, from) + (insertHere ? inserted : '') + value.slice(to);
        result.push(node.type === 'xref' ? { ...node, label: text } : { ...node, text });
        if (insertHere) applied = true;
      } else result.push(node);
    }
    offset = next;
  }
  if (!applied) result.push({ type: 'text', text: inserted });
  return result;
}

export function reconcileInline(nodes: Inline[], text: string, atoms: Record<string, string> = {}) {
  const old = nodes.map(node => inlineValue(node, atoms)).join('');
  let start = 0, tail = 0;
  while (start < old.length && start < text.length && old[start] === text[start]) start++;
  while (tail < old.length - start && tail < text.length - start && old[old.length - tail - 1] === text[text.length - tail - 1]) tail++;
  // Do not split a surrogate pair when a replacement shares its leading unit.
  if (start && /[\uD800-\uDBFF]/.test(old[start - 1])) start--;
  if (tail && /[\uDC00-\uDFFF]/.test(old[old.length - tail])) tail--;
  return editInline(nodes, start, old.length - tail, text.slice(start, text.length - tail), atoms);
}
