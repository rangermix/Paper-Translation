import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { Icon } from '../components';
import './source-workspace.css';

/** A PDF and its correction form share one location while switching mobile views. */
export function SourceWorkspace({ title, evidence, children, onClose, busy = false, location }: {
  title: string; evidence: ReactNode; children: ReactNode; onClose: () => void; busy?: boolean; location?: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const viewId = useId();
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 760px)').matches);
  const [view, setView] = useState<'form' | 'pdf'>('form');
  const [zoom, setZoom] = useState(100);
  useLayoutEffect(() => {
    const element = dialog.current;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : undefined;
    const overflow = document.body.style.overflow;
    element?.showModal(); document.body.style.overflow = 'hidden';
    return () => {
      const restore = document.activeElement === document.body || Boolean(element?.contains(document.activeElement));
      element?.close(); document.body.style.overflow = overflow;
      if (restore && trigger?.isConnected && trigger.getClientRects().length > 0 && !trigger.closest('[inert]')) trigger.focus({ preventScroll: true });
    };
  }, []);
  useEffect(() => {
    const media = window.matchMedia('(max-width: 760px)');
    const changed = () => setMobile(media.matches);
    media.addEventListener('change', changed);
    return () => media.removeEventListener('change', changed);
  }, []);
  return <dialog ref={dialog} className="source-workspace" aria-label={title} aria-busy={busy}
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}
    onKeyDown={event => {
      if (event.key !== 'Tab' || (event.target as Element).closest('dialog') !== event.currentTarget) return;
      const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, summary, [tabindex]')].filter(element => element.tabIndex >= 0 && !element.matches(':disabled') && element.getClientRects().length > 0);
      const first = controls[0], last = controls.at(-1);
      if (!first) { event.preventDefault(); event.currentTarget.focus(); }
      else if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }}>
    <header className="source-workspace-header"><div><h2>{title}</h2>{location && <p className="small muted">{location}</p>}</div>
      <button type="button" className="icon-btn" aria-label="关闭校对工作区" disabled={busy} onClick={onClose}><Icon name="close"/></button>
    </header>
    <p className="small muted source-workspace-note">依据原文 PDF 修正识别结果；保存后创建新来源，已有版本保留。</p>
    {mobile && <div className="source-workspace-tabs" role="group" aria-label="校对视图">
      <button className="btn" type="button" aria-pressed={view === 'form'} aria-controls={`${viewId}-form`} onClick={() => setView('form')}>修改内容</button>
      <button className="btn" type="button" aria-pressed={view === 'pdf'} aria-controls={`${viewId}-pdf`} onClick={() => setView('pdf')}>原文 PDF</button>
    </div>}
    <div className="source-workspace-grid">
      <section className="source-workspace-evidence" id={`${viewId}-pdf`} aria-label="原文 PDF 对照" hidden={mobile && view !== 'pdf'}>
        <div className="source-zoom"><label>页面缩放 <select aria-label="页面缩放" value={zoom} onChange={event => setZoom(Number(event.target.value))}>
          <option value={100}>适合宽度</option><option value={150}>150%</option><option value={200}>200%</option>
        </select></label>{zoom !== 100 && <span className="small muted">可横向移动查看放大后的页面。</span>}</div>
        <div className="source-evidence-scroll"><div style={{ width: `${zoom}%` }}>{evidence}</div></div>
      </section>
      <section className="source-workspace-form" id={`${viewId}-form`} aria-label="原文修改" hidden={mobile && view !== 'form'}>{children}</section>
    </div>
  </dialog>;
}
