import { useState } from 'react';
import { resourceId } from '../domain';
import { languageName } from '../languages';
import type { Preflight } from '../types';
import { ContinueTranslation } from './continue-translation';

export function SavedParseTranslation({ preflight }: { preflight: Preflight }) {
  const [draft, setDraft] = useState('');
  const targets = preflight.translation_targets ?? [];
  if (preflight.status === 'superseded') return <p className="notice">此解析结果已有更新。
    <a href={`#/documents/${resourceId(preflight.document_id)}`}>查看文档的最新解析结果</a></p>;
  return <>
    <p className="notice">原文解析已完成。点击开始翻译，可使用当前服务配置翻译尚未完成的内容。</p>
    <div className="stack">{targets.map(target => <button key={target.draft_id} className="btn primary"
      onClick={() => setDraft(target.draft_id)}>开始翻译 · {languageName(target.target_locale)}</button>)}</div>
    {!targets.length && <a className="btn" href={`#/documents/${resourceId(preflight.document_id)}`}>选择语言并开始翻译</a>}
    {draft && <ContinueTranslation draftId={draft} close={() => setDraft('')}/>}
  </>;
}
