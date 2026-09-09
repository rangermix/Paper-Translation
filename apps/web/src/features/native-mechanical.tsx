import { useEffect, useState } from 'react';
import { PdfLocator } from '../components';
import type { Preflight, SourceBlock } from '../types';

export type NativeRegion = { page: number; bbox: [number, number, number, number]; text: string; page_size: [number, number]; native_indices?: number[] };
export type NativeSnapshot = { generation: number; pages: { page: number; page_size: [number, number]; page_image_sha256?: string; text_regions: Omit<NativeRegion, 'page' | 'page_size'>[] }[]; blocks: {block_id: string; native_text: string; native_regions: NativeRegion[]}[] };

function continuationAfter(source: SourceBlock, blocks: SourceBlock[]) {
  const roots = blocks.filter(b => b.owner_id == null), index = roots.findIndex(b => b.id === source.id);
  const floats: SourceBlock[] = [];
  if (index < 0 || !['paragraph', 'list_item'].includes(source.kind)) return { floats };
  for (const block of roots.slice(index + 1)) {
    if (['figure', 'table', 'math'].includes(block.kind)) { floats.push(block); continue; }
    return { floats, next: block.kind === 'paragraph' && block.parent_id === source.parent_id ? block : undefined };
  }
  return { floats };
}

export function NativeMechanical({ mode, source, region, native, preflight, change }: { mode: string; source: SourceBlock; region: NativeRegion; native: NativeSnapshot; preflight: Preflight; change: (operation?: Record<string, unknown>) => void }) {
  const merge = mode === 'native_merge';
  const [rule, setRule] = useState(merge ? 'remove_line_wrap' : 'restore_native_spacing');
  const [startValue, setStart] = useState(''), [endValue, setEnd] = useState(''), [proofIndex, setProof] = useState('');
  const text = source.normalized_text ?? source.source_text ?? '', start = Number(startValue), end = Number(endValue);
  const selected = [...text].slice(start, end).join('');
  const { next, floats } = continuationAfter(source, preflight.blocks ?? []);
  const proofs = native.blocks.find(b => b.block_id === (merge ? next?.id : source.id))?.native_regions ?? [];
  const continuation = proofIndex === '' ? undefined : proofs[Number(proofIndex)];
  const needsContinuation = merge || rule !== 'restore_native_spacing';
  const pageNumbers = [...new Set([region.page, ...(needsContinuation && continuation ? [continuation.page] : [])])];
  const hashes = Object.fromEntries(pageNumbers.map(number => [String(number), native.pages.find(p => p.page === number)?.page_image_sha256]));
  const originalProof = (proof: NativeRegion) => ({ page: proof.page, bbox: proof.bbox, quote: proof.text });
  const orderedGlyphs = (proof: NativeRegion) => !!proof.native_indices?.length && proof.native_indices.length === [...proof.text].length;
  const spanReady = startValue !== '' && endValue !== '' && Number.isSafeInteger(start) && Number.isSafeInteger(end) && start >= 0 && end > start && end <= [...text].length;
  const ready = native.generation === preflight.generation && orderedGlyphs(region) && Object.values(hashes).every(hash => !!hash?.match(/^[a-f0-9]{64}$/)) && (merge ? !!next : spanReady) && (!needsContinuation || !!continuation && orderedGlyphs(continuation));
  const operation = !ready ? undefined : merge ? { kind: 'merge_native_continuation', block_ids: [source.id, next!.id], rule, continuation_evidence: originalProof(continuation!), page_image_sha256s: hashes } : { kind: 'normalize_native_span', block_id: source.id, start, end, rule, ...(needsContinuation ? { continuation_evidence: originalProof(continuation!) } : {}), page_image_sha256s: hashes };
  const serialized = JSON.stringify(operation);
  // Bind confirmation to the exact proposed fields; parent render does not reset it.
  useEffect(() => { change(serialized ? JSON.parse(serialized) : undefined); }, [serialized, change]);
  const continuationUrl = preflight.pages?.find(p => p.page === continuation?.page)?.page_image_url;
  return <>
    <p className="field-note">仅按已保存的原生字形、位置和页图恢复机械提取。不会提交任意替换文字；服务端还会验证确切出现位置、行序及保护内容。</p>
    <label className="field">机械清理规则<select value={rule} onChange={e => { setRule(e.target.value); setProof(''); }}>
      {!merge && <option value="restore_native_spacing">恢复原生空白（仅空白差异）</option>}
      <option value="remove_line_wrap">去掉换行断词连字符（拼回同一个词）</option>
      <option value="retain_line_hyphen">保留原词连字符（如 all-to-all）</option>
    </select></label>
    {merge ? <>
      <label className="field">续接来源块<select disabled value={next?.id ?? ''}><option value={next?.id ?? ''}>{next ? `${next.id} · ${next.normalized_text ?? next.source_text}` : '没有符合顺序的续接段落'}</option></select></label>
      <p>保留中间图表与公式：{floats.map(b => b.id).join('、') || '无'}</p>
      <p className="small muted">第一块末行与第二块首行须在同页或相邻页；中间不能夹有其他正文。保留原块、位置及图表审计记录。</p>
    </> : <>
      <label className="field">机械片段起点（Unicode 字符）<input className="input" type="number" min="0" step="1" value={startValue} onChange={e => setStart(e.target.value)}/></label>
      <label className="field">机械片段终点（不含此字符）<input className="input" type="number" min="1" step="1" value={endValue} onChange={e => setEnd(e.target.value)}/></label>
      <p className="small">只选择当前提取文字的目标片段；补充平面字符按一个字符计数，不得切断数字、公式或引用。</p>
      <pre className="source-block">{spanReady ? selected : '请选择有效的原文片段'}</pre>
    </>}
    {needsContinuation && <>
      <label className="field">续接原生行证据<select value={proofIndex} onChange={e => setProof(e.target.value)}><option value="">请选择原件确切下一行</option>{proofs.map((proof, index) => <option key={index} value={index}>页 {proof.page} · {proof.text.slice(0, 100)}</option>)}</select></label>
      {continuation && <><pre className="source-block">{continuation.text}</pre><PdfLocator originalUrl={preflight.original_url} documentId={preflight.document_id} locators={[{page: continuation.page, page_size: continuation.page_size, bbox: continuation.bbox, page_image_url: continuationUrl}]}/></>}
    </>}
    <p className="field-note mono">原页 SHA-256：{Object.entries(hashes).map(([number, hash]) => `页 ${number} ${hash ?? '缺失'}`).join('；')}</p>
    {!ready && <p className="field-note warn">需要完整原生字形证据、所有证据页 SHA、当前版本及有效选择，才能提交。</p>}
  </>;
}
