import { t } from '../i18n';
import { useId, useRef, useState } from 'react';
import { api, etagFor } from '../api';
import { ActionFeedback, PdfLocator } from '../components';
import { resourceId, sourceTextEdit } from '../domain';
import { useAction } from '../hooks';
import type { Document, Draft } from '../types';
import { SourceWorkspace } from './source-workspace';
import { useSourceLeaveProtection } from './source-leave-protection';

type CreatedSource = { id: string; source_hash: string; generation: number };

export function DraftSourceCorrection({ draft, documentSnapshot, onClose, onSaved }: {
  draft: Draft; documentSnapshot?: Document; onClose: () => void; onSaved: () => void;
}) {
  // The displayed original and its CAS basis stay tied to this correction session.
  const baseline = useRef({ draft, document: documentSnapshot }).current;
  const source = baseline.draft;
  const inputId = useId();
  const [blockId, setBlockId] = useState(source.segments[0]?.block_id ?? '');
  const segment = source.segments.find(item => item.block_id === blockId);
  const [kind, setKind] = useState('replace_text');
  const [text, setText] = useState(segment?.source_text ?? '');
  const [reason, setReason] = useState('');
  const [offset, setOffset] = useState('0');
  const initialOrder = (source.source?.reading_order ?? []).join('\n');
  const [order, setOrder] = useState(initialOrder);
  const [created, setCreated] = useState<CreatedSource>();
  const action = useAction();
  const dirty = !created && Boolean(reason || kind !== 'replace_text' || text !== (segment?.source_text ?? '') || offset !== '0' || order !== initialOrder);
  const protection = useSourceLeaveProtection(dirty, action.pending);
  const close = () => { void protection.request(onClose); };
  return <>
    <SourceWorkspace title={t("修正原文识别")} onClose={close} busy={action.pending}
      location={segment ? t("段落 {value1}{value2}", { value1: segment.block_id, value2: segment.locators?.[0] ? t(" · 第 {value1} 页", { value1: segment.locators[0].page }) : t(" · 无精确页码") }) : undefined}
      evidence={<PdfLocator originalUrl={source.original_url} documentId={source.document_id} locators={segment?.locators}/>}>
      <form onSubmit={event => {
        event.preventDefault();
        if (!segment?.locators?.length || created) return;
        void action.run(async () => {
          const next = await api<CreatedSource>(`/sources/${resourceId(source.source_revision_id)}/corrections`, {
            method: 'POST', etag: etagFor(baseline.document), body: {
              reason, evidence: { page: segment.locators![0].page, bbox: segment.locators![0].bbox, quote: segment.source_text },
              operations: [kind === 'replace_text' ? { kind, block_id: blockId, ...sourceTextEdit(segment.source_text, text) }
                : kind === 'split' ? { kind, block_id: blockId, offset: Number(offset) }
                  : { kind, block_ids: order.split(/[\s,，]+/).filter(Boolean) }],
            },
          });
          setCreated(next); onSaved();
        }, "已创建来源草稿；请核对所提交内容，再确认新来源。");
      }}>
        <fieldset disabled={action.pending || Boolean(created)} className="source-correction-fields">
          <label className="field">{t("来源段落")}<select value={blockId} onChange={event => {
            const nextId = event.target.value;
            void protection.request(() => {
              setBlockId(nextId); setText(source.segments.find(item => item.block_id === nextId)?.source_text ?? '');
              setReason(''); setKind('replace_text'); setOffset('0'); setOrder(initialOrder);
            });
          }}>{source.segments.map(item => <option key={item.block_id}>{item.block_id}</option>)}</select></label>
          <label className="field">{t("机械修正操作")}<select value={kind} onChange={event => setKind(event.target.value)}>
            <option value="replace_text">{t("修正机械提取字符")}</option><option value="reorder">{t("调整根块阅读顺序")}</option>
            <option value="split">{t("拆分正文段落")}</option><option value="merge">{t("合并相邻正文段落")}</option>
          </select></label>
          <details><summary>{t("当前识别原文")}</summary><pre>{segment?.source_text}</pre></details>
          {kind === 'replace_text' ? <div className="field"><label htmlFor={`${inputId}-text`}>{t("核对后的原文")}</label><textarea id={`${inputId}-text`} required value={text} onChange={event => setText(event.target.value)}/></div>
            : kind === 'split' ? <label className="field">{t("Unicode 字符拆分位置")}<input className="input" type="number" min="1" step="1" value={offset} onChange={event => setOffset(event.target.value)}/></label>
              : <label className="field">{kind === 'reorder' ? t("完整根块顺序（每行一个 ID，不得增删）") : t("要合并的相邻正文 ID（按原顺序，每行一个）")}<textarea required value={order} onChange={event => setOrder(event.target.value)}/></label>}
          <div className="field"><label htmlFor={`${inputId}-reason`}>{t("原件证据与机械修正理由")}</label><textarea id={`${inputId}-reason`} required value={reason} onChange={event => setReason(event.target.value)}/></div>
        </fieldset>
        <ActionFeedback {...action}/>
        {created && <p className="notice">{t("来源草稿已创建，尚未确认新来源。所提交内容已锁定，可对照原文 PDF 核查。")}</p>}
        <div className="source-workspace-actions">
          {!created ? <button className="btn primary" disabled={action.pending || !reason.trim() || !segment?.locators?.length}>{t("创建来源修正")}</button>
            : <button type="button" className="btn primary" disabled={action.pending} onClick={() => void action.run(async () => {
              await api(`/sources/drafts/${resourceId(created.id)}/confirm`, { method: 'POST', etag: etagFor(created), body: { source_hash: created.source_hash } });
              onSaved(); onClose();
            })}>{t("保存新来源修订")}</button>}
          <button className="btn" type="button" disabled={action.pending} onClick={close}>{created ? t("关闭") : t("取消校对")}</button>
          {dirty && <span className="small muted">{t("有未保存的校对输入")}</span>}
        </div>
      </form>
    </SourceWorkspace>
    {protection.dialog}
  </>;
}
