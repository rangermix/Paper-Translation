import { useState } from 'react';
import { ErrorNotice, Loading } from '../components';
import { useResource } from '../hooks';
import type { Document, Page } from '../types';

export function documentChoiceLabel(document: Document) {
  const author = document.bibliography?.authors[0]?.name;
  const filename = document.original_filename ?? document.source_asset?.filename;
  const date = document.bibliography?.year ?? document.created_at?.slice(0, 10);
  return [document.title, author, date, filename].filter(Boolean).join(' · ');
}

export function DocumentPicker({ label, value, onChange, selectedDocument, allowAll = false, disabled = false }: {
  label: string; value: string; onChange: (value: string) => void; selectedDocument?: Document;
  allowAll?: boolean; disabled?: boolean;
}) {
  const [query, setQuery] = useState('');
  const [submitted, setSubmitted] = useState('');
  const [cursor, setCursor] = useState('');
  const params = new URLSearchParams({ limit: '30', lifecycle: 'all' });
  if (submitted) params.set('q', submitted);
  if (cursor) params.set('cursor', cursor);
  const result = useResource<Page<Document>>(`/documents?${params}`);
  const documents = result.data?.items ?? [];
  return <div className="field document-picker" role="group" aria-label={`${label}选择器`}>
    <label>{label}<select aria-label={label} value={value} disabled={disabled} onChange={event => onChange(event.target.value)}>
      <option value="">{allowAll ? '全库文档' : '请选择文档'}</option>
      {value && !documents.some(document => document.id === value) && <option value={value}>{selectedDocument ? documentChoiceLabel(selectedDocument) : '所选文档暂不可用'}</option>}
      {documents.map(document => <option key={document.id} value={document.id}>{documentChoiceLabel(document)}</option>)}
    </select></label>
    <div className="stack"><input className="input" aria-label={`${label}：搜索标题`} placeholder="输入标题查找文档" value={query} disabled={disabled} onChange={event => setQuery(event.target.value)}
      onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); setSubmitted(query.trim()); setCursor(''); } }}/>
      <button type="button" className="btn sm" disabled={disabled} onClick={() => { setSubmitted(query.trim()); setCursor(''); }}>查找文档</button></div>
    <ErrorNotice error={result.error} retry={result.reload}/>{result.loading && <Loading/>}
    {result.data && !documents.length && <p role="status" className="small muted">{submitted ? '没有找到匹配的文档，请换一个标题。' : '文库暂无可选文档。'}</p>}
    <div className="stack">{cursor && <button type="button" className="btn sm" disabled={disabled} onClick={() => setCursor('')}>返回首批文档</button>}
      {result.data?.next_cursor && <button type="button" className="btn sm" disabled={disabled} onClick={() => setCursor(result.data!.next_cursor!)}>更多文档</button>}</div>
  </div>;
}
