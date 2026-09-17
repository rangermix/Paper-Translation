import type { Inline, Locator } from './types';
export function inlineText(nodes: Inline[] = [], atoms: Record<string, string> = {}): string {
  return nodes.map(node => node.type === 'text' ? node.text : atoms[node.ref ?? node.id ?? node.ref_id ?? ''] ?? `[${node.ref ?? node.id ?? node.ref_id ?? '保护内容'}]`).join('');
}
export function replaceTextNodes(nodes: Inline[], values: string[]): Inline[] { let i = 0; return nodes.map(n => n.type === 'text' ? { type: 'text', text: values[i++] ?? n.text } : n); }
export function codePointOffset(text: string, utf16Offset: number) { return Array.from(text.slice(0, utf16Offset)).length; }
export function sourceTextEdit(before: string, after: string) {
  const old = Array.from(before), next = Array.from(after);
  let start = 0, tail = 0;
  while (start < old.length && start < next.length && old[start] === next[start]) start++;
  while (tail < old.length - start && tail < next.length - start && old[old.length - 1 - tail] === next[next.length - 1 - tail]) tail++;
  return { start, end: old.length - tail, text: next.slice(start, next.length - tail).join('') };
}
export function locatorStyle(locator: Locator) {
  const [x0, y0, x1, y1] = locator.bbox;
  const [w, h] = locator.page_size;
  if (![x0, y0, x1, y1, w, h].every(Number.isFinite) || locator.page < 1 || w <= 0 || h <= 0 || x0 < 0 || y0 < 0 || x1 <= x0 || y1 <= y0 || x1 > w || y1 > h) throw new Error('无效的原件定位');
  return { left: `${x0 / w * 100}%`, top: `${y0 / h * 100}%`, width: `${(x1 - x0) / w * 100}%`, height: `${(y1 - y0) / h * 100}%` };
}
export function canConfirmPreflight(preflight: { status: string; unresolved_blocks: number; can_translate?: boolean }, _sourceConfirmed: boolean, externalConfirmed: boolean, budget: number, costControlled = true) { return preflight.can_translate !== false && !['failed', 'superseded', 'sealed'].includes(preflight.status) && externalConfirmed && (!costControlled || Number.isSafeInteger(budget) && budget > 0); }
export function canResumeJob(status: string) { return ['paused', 'waiting_budget', 'waiting_config', 'waiting_configuration'].includes(status); }
const labels: Record<string, string> = { queued: '排队中', leased: '执行中', committed: '结果已保存', received: '已收到结果', settled: '用量已记录', superseded: '已有更新版本', unavailable: '暂无可用结果', waiting_configuration: '等待配置', draft: '可编辑', incomplete: '未完成', not_requested: '尚未执行',  extracted: '已提取', with_warnings: '有提示', completed_with_warnings: '已完成，有提示', partially_completed: '部分完成', not_checked: '尚未检查', stale: '检查结果待更新', source_only: '原件已保存', inspecting: '检查 PDF', parsing: '解析原文', preflight: '提取结果可查看', translating: '翻译中', checking: '质量检查', needs_review: '历史任务待继续', ready: '已就绪', published: '已发布', sealed: '已封存', building: '构建中', completed: '已完成', succeeded: '已完成', pending: '排队中', running: '处理中', paused: '已暂停', cancel_requested: '正在取消', cancelled: '已取消', failed: '失败', outcome_unknown: '结果未知 · 可能已计费', waiting_config: '等待翻译条件齐备', waiting_budget: '等待预算', OCR_REQUIRED: '此页暂无可靠文字', verified: '已验证', human_reviewed: '已人工确认', machine_checked: '已机器检查', not_reviewed: '未核对 · 可选', archived: '已归档', active: '常规文档' };
export function statusLabel(value?: string) { return value ? labels[value] ?? '状态待确认' : '未提供'; }
export function money(value?: number | null, currency = 'USD') { return value === undefined || value === null ? '未计算' : `${currency} ${(value / 1_000_000).toFixed(6)}`; }
export function localUrl(url: string | undefined, fallback = '#') { return url?.startsWith('/') && !url.startsWith('//') && !url.includes('\\') ? url : fallback; }
export function resourceId(value: string) { return encodeURIComponent(value); }
