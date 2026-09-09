import { useCallback, useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, ErrorNotice, Loading, Modal, PdfLocator } from '../components';
import { useAction, useResource } from '../hooks';
import { resourceId } from '../domain';
import type { Preflight } from '../types';
import { NativeMechanical, type NativeRegion, type NativeSnapshot } from './native-mechanical';

export function ImportCorrections({ preflight, onClose }: { preflight: Preflight; onClose: () => void }) {
  const native = useResource<NativeSnapshot>(`/imports/${resourceId(preflight.import_id)}/native-regions`);
  const action = useAction();
  const [selected, setSelected] = useState(0);
  const [mechanicalOperation, setMechanicalOperation] = useState<Record<string, unknown>>();
  const mechanicalChanged = useCallback((operation?: Record<string, unknown>) => { setMechanicalOperation(operation); setChecked(false); setReason(''); }, []);
  const [blockId, setBlockId] = useState('');
  const [after, setAfter] = useState('');
  const [reason, setReason] = useState('');
  const [checked, setChecked] = useState(false);
  const [mode, setMode] = useState('native');
  const [allRegions, setAllRegions] = useState(false);
  const [footnoteTarget, setFootnoteTarget] = useState('');
  const [markerStart, setMarkerStart] = useState('');
  const [markerEnd, setMarkerEnd] = useState('');
  const [joiner, setJoiner] = useState(' ');
  const [prefix, setPrefix] = useState('');
  const [suffix, setSuffix] = useState('');
  const [cropValues, setCropValues] = useState<string[] | null>(null);
  const regions = allRegions ? native.data?.pages.flatMap(page => page.text_regions.map(region => ({...region, page: page.page, page_size: page.page_size}))) ?? [] : preflight.unresolved?.filter(r => r.text && r.bbox).flatMap(r => {
    const page = native.data?.pages.find(p => p.page === r.page);
    const region = page?.text_regions.find(n => n.text === r.text && JSON.stringify(n.bbox) === JSON.stringify(r.bbox));
    return region && page ? [{ ...region, page: page.page, page_size: page.page_size }] : [];
  }) ?? [];
  const region = regions[selected];
  const mapped = native.data?.blocks.filter(b => b.native_regions.some(r => r.page === region?.page && JSON.stringify(r.bbox) === JSON.stringify(region?.bbox))) ?? [];
  const block = mapped.find(b => b.block_id === blockId) ?? mapped[0];
  const source = preflight.blocks?.find(b => b.id === block?.block_id);
  const sourceText = source?.normalized_text ?? source?.source_text ?? '';
  const page = native.data?.pages.find(p => p.page === region?.page);
  const pageImageUrl = preflight.pages?.find(p => p.page === region?.page)?.page_image_url ?? (source?.locators ?? source?.provenance ?? []).find(loc => loc.page === region?.page)?.page_image_url;
  const values = cropValues ?? region?.bbox.map(String) ?? ['', '', '', ''];
  const crop = values.map(Number) as NativeRegion['bbox'];
  const [x0, y0, x1, y1] = crop;
  const validCrop = Boolean(region && values.every(v => v.trim() !== '' && Number.isFinite(Number(v))) && x0 >= 0 && y0 >= 0 && x1 > x0 && y1 > y0 && x1 <= region.page_size[0] && y1 <= region.page_size[1] && x0 <= region.bbox[0] && y0 <= region.bbox[1] && x1 >= region.bbox[2] && y1 >= region.bbox[3]);
  const mechanicalMode = mode === 'native_span' || mode === 'native_merge';
  const mathMode = mode === 'math_crop' || mode === 'math_annotation';
  const annotationKind = Boolean(source && ['paragraph', 'caption', 'table_cell', 'list_item', 'heading', 'footnote'].includes(source.kind));
  const paragraphBox = (source?.provenance ?? source?.locators ?? []).find(loc => {
    if (loc.page !== region?.page) return false;
    const margins = [loc.bbox[0] - x0, loc.bbox[1] - y0, x1 - loc.bbox[2], y1 - loc.bbox[3]];
    if (margins.every(margin => margin <= 0)) return true;
    const proofs = mode === 'math_annotation' ? page?.text_regions ?? [] : region ? [region] : [];
    return Math.max(...margins) <= 2 && margins.every((margin, edge) => margin <= 0 || proofs.some(proof => proof.bbox[0] >= x0 && proof.bbox[1] >= y0 && proof.bbox[2] <= x1 && proof.bbox[3] <= y1 && Math.abs(proof.bbox[edge] - crop[edge]) <= 1));
  });
  const boundedCrop = Boolean(paragraphBox && (x1 - x0) * (y1 - y0) < (paragraphBox.bbox[2] - paragraphBox.bbox[0]) * (paragraphBox.bbox[3] - paragraphBox.bbox[1]) * .5 && (x1 - x0) * (y1 - y0) <= region!.page_size[0] * region!.page_size[1] * .1);
  const exactSplit = Boolean((prefix.trim() || suffix.trim()) && sourceText.startsWith(prefix) && sourceText.endsWith(suffix) && prefix.length + suffix.length < sourceText.length);
  const middle = exactSplit ? sourceText.slice(prefix.length, suffix.length ? -suffix.length : undefined) : '';
  const mathReady = (mode === 'math_annotation' ? annotationKind : source?.kind === 'paragraph') && Boolean(page?.page_image_sha256?.match(/^[a-f0-9]{64}$/i)) && validCrop && boundedCrop && exactSplit && Boolean(middle.trim()) && [...middle].length <= [...sourceText].length / 2;
  const footnotes = preflight.blocks?.filter(b => b.kind === 'footnote' && (b.provenance ?? b.locators ?? []).some(loc => loc.page === region?.page)) ?? [];
  const targetFootnote = footnotes.find(b => b.id === footnoteTarget);
  const start = Number(markerStart), end = Number(markerEnd);
  const marker = [...sourceText].slice(start, end).join('');
  const footnoteReady = Boolean(source && targetFootnote && markerStart.trim() && markerEnd.trim() && Number.isSafeInteger(start) && Number.isSafeInteger(end) && start >= 0 && end > start && end <= [...sourceText].length && marker && marker === region?.text.trim() && page?.page_image_sha256?.match(/^[a-f0-9]{64}$/i));
  const resetSplit = () => { setChecked(false); setPrefix(''); setSuffix(''); setCropValues(null); setMode('native'); setFootnoteTarget(''); setMarkerStart(''); setMarkerEnd(''); setJoiner(' '); setMechanicalOperation(undefined); };
  const roots = preflight.blocks?.filter(b => b.owner_id == null) ?? [];
  const currentIndex = roots.findIndex(b => b.id === source?.id);
  const nextRoot = currentIndex >= 0 ? roots[currentIndex + 1] : undefined;
  const continuation = source && ['paragraph','list_item'].includes(source.kind) && nextRoot?.kind === 'paragraph' && nextRoot.parent_id === source.parent_id && (nextRoot.provenance ?? nextRoot.locators ?? []).every(loc => loc.page === region?.page) ? nextRoot : undefined;
  const terminal = region?.text.match(/([A-Za-z]+)[\-\u00ad\u0002]\s*$/)?.[1];
  const fragment = sourceText.match(/([A-Za-z]+)-?$/)?.[1];
  const joinedWord = Boolean(terminal && terminal === fragment && /^[a-z]/.test(continuation?.normalized_text ?? continuation?.source_text ?? ''));
  const continuationReady = Boolean(continuation && page?.page_image_sha256?.match(/^[a-f0-9]{64}$/i) && (joiner === ' ' || joinedWord));
  const insertion = after || roots[0]?.id;
  return <Modal title="对照原生 PDF 修正提取" onClose={onClose}>
    <p>对照已保存的原始字符与页图修正来源。每次产生新来源草稿并重新计算覆盖；公式可依据原页精确裁图，前后正文继续保留和翻译。</p>
    <ErrorNotice error={native.error} retry={native.reload}/>{native.loading && <Loading/>}<ActionFeedback {...action}/>
    <label className="check"><input type="checkbox" checked={allRegions} onChange={event => {setAllRegions(event.target.checked); setSelected(0); setBlockId(''); resetSplit();}}/>查看全部原生区域（含已覆盖）</label>
    {regions.length > 0 && region ? <form onSubmit={e => { e.preventDefault(); void action.run(async () => {
      const evidence = { page: region.page, bbox: region.bbox, quote: region.text };
      if (mechanicalMode && !mechanicalOperation) return;
      if (mathMode && !mathReady) return;
      if (mode === 'footnote' && !footnoteReady) return;
      if (mode === 'continuation' && !continuationReady) return;
      const operations = mechanicalMode ? [{...mechanicalOperation, visual_review_confirmed: checked}] : mode === 'math_annotation' ? [{kind: 'annotate_math_crop', block_id: block!.block_id, start: [...prefix].length, end: [...prefix].length + [...middle].length, page: region.page, bbox: crop, page_image_sha256: page!.page_image_sha256, visual_review_confirmed: checked}] : mode === 'continuation' ? [{kind: 'merge_continuation', block_ids: [source!.id, continuation!.id], joiner, page_image_sha256: page!.page_image_sha256, visual_review_confirmed: checked}] : mode === 'footnote' ? [{kind: 'annotate_footnote', block_id: block!.block_id, start, end, target_block_id: targetFootnote!.id, page_image_sha256: page!.page_image_sha256, visual_review_confirmed: checked}] : mode === 'math_crop' ? [{kind: 'split_with_math_crop', block_id: block!.block_id, page: region.page, bbox: crop, prefix, suffix, page_image_sha256: page!.page_image_sha256, visual_review_confirmed: checked}] : block && source ? [{kind: 'replace_text', block_id: block.block_id, start: 0, end: [...sourceText].length, text: block.native_text}] : [{kind: 'recover_region', ...evidence, after_block_id: insertion}];
      const next = await api<{id: string}>(`/imports/${resourceId(preflight.import_id)}/corrections`, {method: 'POST', etag: etagFor(preflight), body: {reason, evidence, operations}});
      onClose(); location.hash = `/preflight/${next.id}`;
    }); }}>
      <label className="field">待核对的原生文字区域<select value={selected} onChange={e => {setSelected(Number(e.target.value)); setBlockId(''); resetSplit();}}>{regions.map((r, i) => <option key={i} value={i}>页 {r.page} · {r.text.slice(0, 65)}</option>)}</select></label>
      <PdfLocator originalUrl={preflight.original_url} documentId={preflight.document_id} locators={[{page_image_url: pageImageUrl, page: region.page, bbox: region.bbox, page_size: region.page_size}]}/>
      <h3>PDF 原生字符</h3><pre className="source-block">{region.text}</pre>
      {mapped.length ? <><label className="field">恢复对应来源块<select value={block?.block_id} onChange={e => {setBlockId(e.target.value); resetSplit();}}>{mapped.map(b => <option key={b.block_id}>{b.block_id}</option>)}</select></label><div className="review-grid"><div><h3>当前解析结果</h3><pre>{sourceText}</pre></div><div><h3>该块所有原生区域全文</h3><pre>{block?.native_text}</pre></div></div><label className="field">修正方式<select aria-label="修正方式" value={mode} onChange={e => {setMode(e.target.value); setChecked(false); setReason(''); setMechanicalOperation(undefined);}}><option value="native">按原生字符恢复全文</option><option value="native_span" disabled={!source || !['paragraph', 'list_item', 'caption', 'reference', 'heading', 'footnote'].includes(source.kind)}>按原生证据清理指定机械片段</option><option value="native_merge" disabled={!source || !['paragraph', 'list_item'].includes(source.kind)}>连接图表前后的原生续接段落</option><option value="continuation" disabled={!continuation || !page?.page_image_sha256}>连接同页跨栏续接段落</option><option value="footnote" disabled={!page?.page_image_sha256 || !footnotes.length}>关联同页原文脚注标记</option><option value="math_annotation" disabled={!annotationKind || !page?.page_image_sha256}>将原数学片段关联到独立原页裁图（保留图注或表格归属）</option><option value="math_crop" disabled={source?.kind !== 'paragraph' || !page?.page_image_sha256}>将行内公式保留为原页裁图</option></select></label></> : <label className="field">将确实遗漏的原生段落放在此根块之后<select value={insertion} onChange={e => {setAfter(e.target.value); setChecked(false);}}>{roots.map(b => <option key={b.id} value={b.id}>{b.id} · {(b.normalized_text ?? b.source_text ?? '').slice(0, 35)}</option>)}</select></label>}
      {mechanicalMode && source && native.data && <NativeMechanical key={`${mode}:${source.id}:${region.page}:${region.bbox.join(',')}`} mode={mode} source={source} region={region} native={native.data} preflight={preflight} change={mechanicalChanged}/>}
      {mathMode && <>
        {mode === 'math_annotation' && <p className="notice">保留当前块的原文及图注、表格归属，仅为所选数学片段添加可点击引用。原页公式图会作为独立块显示，不表示原文具有行内公式排版。</p>}
        <p className="field-note">从当前解析内容精确复制公式前后的正文。中间内容仅用原 PDF 图像替代，不推测公式文本；裁图必须包含所选证据区域，且不能覆盖整段正文。</p>
        <label className="field">公式前的原文（精确前缀）<textarea value={prefix} onChange={e => {setPrefix(e.target.value); setChecked(false);}}/></label>
        <label className="field">公式后的原文（精确后缀）<textarea value={suffix} onChange={e => {setSuffix(e.target.value); setChecked(false);}}/></label>
        <p className="field-note">{exactSplit ? '以下当前解析片段将由原公式图替代：' : '前后缀必须与当前原文逐字匹配，且保留非空的公式片段。'}</p>{exactSplit && <pre className="source-block">{middle}</pre>}
        <div className="two-cols">{['x0', 'y0', 'x1', 'y1'].map((label, index) => <label className="field" key={label}>公式裁图 {label}<input className="input" type="number" step="any" value={values[index]} onChange={e => {setCropValues(values.map((v, i) => i === index ? e.target.value : v)); setChecked(false);}}/></label>)}</div>
        {validCrop && <PdfLocator originalUrl={preflight.original_url} documentId={preflight.document_id} locators={[{page_image_url: pageImageUrl, page: region.page, bbox: crop, page_size: region.page_size}]}/>}
        {(!validCrop || !boundedCrop) && <p className="error">裁图须在对应段落和页面范围内，包含所选原生证据，并留出前后正文。</p>}
        <p className="field-note mono">原页 SHA-256：{page?.page_image_sha256 ?? '尚不可用'}</p>
      </>}
      {mode === 'continuation' && <>
        <p className="field-note">仅连接同页阅读顺序相邻的来源块，保留第一块的段落或项目符号属性。选中的原生证据必须来自第一块末行；跨栏断词须有原件行末连字符证明。</p>
        <label className="field">继续本段的相邻来源块<select value={continuation?.id ?? ''} disabled><option value={continuation?.id ?? ''}>{continuation ? `${continuation.id} · ${continuation.normalized_text ?? continuation.source_text}` : '没有可续接的相邻段落'}</option></select></label>
        <label className="field">连接方式<select aria-label="连接方式" value={joiner} onChange={event => {setJoiner(event.target.value);setChecked(false);}}><option value=" ">段落之间保留一个空格</option><option value="" disabled={!joinedWord}>恢复有原件证明的跨栏断词</option></select></label>
        <p className="field-note mono">原页 SHA-256：{page?.page_image_sha256 ?? '尚不可用'}</p>
      </>}
      {mode === 'footnote' && <>
        <p className="field-note">只把原文中的既有标记关联到同页脚注，原始文字不改写。起止位置按 Unicode 字符计数，补充平面字符也算一个字符。</p>
        <label className="field">标记起点（Unicode 字符）<input className="input" type="number" min="0" step="1" value={markerStart} onChange={e => {setMarkerStart(e.target.value); setChecked(false);}}/></label>
        <label className="field">标记终点（不含此字符）<input className="input" type="number" min="1" step="1" value={markerEnd} onChange={e => {setMarkerEnd(e.target.value); setChecked(false);}}/></label>
        <label className="field">同页目标脚注<select value={footnoteTarget} onChange={e => {setFootnoteTarget(e.target.value); setChecked(false);}}><option value="">请选择确切脚注</option>{footnotes.map(footnote => <option key={footnote.id} value={footnote.id}>{footnote.id} · {footnote.normalized_text ?? footnote.source_text}</option>)}</select></label>
        <p className="field-note">当前选中的原标记：<code>{marker || '尚未选择'}</code>；必须与当前原生证据逐字匹配。</p>
        <p className="field-note mono">原页 SHA-256：{page?.page_image_sha256 ?? '尚不可用'}</p>
      </>}
      <label className="field">原件核对记录与理由<textarea required value={reason} onChange={e => setReason(e.target.value)}/></label>
      <label className="check"><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)}/>{mechanicalMode ? '我已核对选中片段与原生字形证据，确认所选机械规则和续接位置；不新增或润色原文。' : mode === 'continuation' ? '我已对照原页，确认这两个相邻块是同一段落或同一项目，连接方式有原文证明。' : mode === 'footnote' ? '我已对照原页，确认所选标记指向同页这条脚注，原文不会改写。' : mathMode ? '我已逐字核对公式前后正文，并确认裁图完整包含原公式，没有裁入无关正文。' : '我已对照高亮的原 PDF，确认恢复内容与阅读位置。'}</label>
      <button className="btn primary section-title" disabled={action.pending || !checked || !reason.trim() || (mechanicalMode ? !mechanicalOperation : mode === 'continuation' ? !continuationReady : mode === 'footnote' ? !footnoteReady : mathMode ? !mathReady : !block && !insertion)}>创建新来源草稿并重检覆盖</button>
    </form> : !native.loading && <p className="notice">没有可按原生文字证据直接恢复的区域。扫描页、未映射图形或复杂结构仍需对应的解析修复，不能跳过覆盖门禁。</p>}
  </Modal>;
}
