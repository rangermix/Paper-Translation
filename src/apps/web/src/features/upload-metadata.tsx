import { useEffect, useState } from 'react';
import { api } from '../api';
import { resourceId } from '../domain';
import type { Upload } from '../types';
import { BibliographyLine, metadataStatusLabel } from './bibliography';

const pending = (status?: string | null) => status === 'pending' || status === 'retrying';

export function UploadMetadata({ upload }: { upload: Upload }) {
  const [current, setCurrent] = useState(upload);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    if (!pending(upload.metadata_status)) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        const result = await api<Upload>(`/uploads/${resourceId(upload.upload_id)}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setCurrent(result);
        if (pending(result.metadata_status)) timer = setTimeout(read, 2000);
      } catch {
        if (!controller.signal.aborted) setUnavailable(true);
      }
    }
    void read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [upload.upload_id, upload.metadata_status]);
  if (!current.metadata_status) return null;
  return <div aria-live="polite">
    <p className="small muted">{unavailable ? '文献信息稍后可在文档详情查看。' :
      `${current.bibliography?.service === 'crossref' ? 'Crossref · ' : ''}${metadataStatusLabel(current.metadata_status)}`}</p>
    {current.bibliography && <><strong>{current.bibliography.title}</strong><BibliographyLine doc={current}/></>}
  </div>;
}
