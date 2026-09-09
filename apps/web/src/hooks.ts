import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
export function useResource<T>(path: string | null, pollMs = 0) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<Error>();
  const [loading, setLoading] = useState(Boolean(path));
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision(n => n + 1), []);
  const lastPath = useRef(path);
  useEffect(() => {
    if (!path) { setData(undefined); setLoading(false); return; }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    if (lastPath.current !== path) { setData(undefined); setError(undefined); setLoading(true); lastPath.current = path; }
    async function read() {
      try { const value = await api<T>(path!, { signal: controller.signal }); if (!controller.signal.aborted) { setData(value); setError(undefined); } }
      catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason : new Error(String(reason))); }
      finally { if (!controller.signal.aborted) { setLoading(false); if (pollMs) timer = setTimeout(read, pollMs); } }
    }
    void read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [path, pollMs, revision]);
  return { data, error, loading, reload, setData };
}
export function useAction() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error>();
  const [notice, setNotice] = useState('');
  const running = useRef(false);
  const run = async (action: () => Promise<unknown>, success = '') => {
    if (running.current) return;
    running.current = true; setPending(true); setError(undefined); setNotice('');
    try { await action(); setNotice(success); }
    catch (reason) { setError(reason instanceof Error ? reason : new ApiError(0, 'UNKNOWN_ERROR', String(reason))); }
    finally { running.current = false; setPending(false); }
  };
  return { run, pending, error, notice, clear: () => { setError(undefined); setNotice(''); } };
}
export function useRoute() {
  const read = () => location.hash.replace(/^#\/?/, '').split('/').map(decodeURIComponent);
  const [parts, setParts] = useState(read);
  useEffect(() => { const onChange = () => { setParts(read()); window.scrollTo(0, 0); }; window.addEventListener('hashchange', onChange); return () => window.removeEventListener('hashchange', onChange); }, []);
  return { page: parts[0] || 'library', id: parts[1], extra: parts[2] };
}
export function useJobEvents(id: string | undefined, reload: () => void) {
  const [connection, setConnection] = useState('polling');
  useEffect(() => {
    if (!id || typeof EventSource === 'undefined') return;
    const stream = new EventSource(`/api/v1/jobs/${encodeURIComponent(id)}/events`);
    stream.onopen = () => setConnection('live');
    stream.onerror = () => setConnection('polling');
    stream.onmessage = reload;
    stream.addEventListener('snapshot_required', reload);
    stream.addEventListener('job', reload);
    stream.addEventListener('progress', reload);
    stream.addEventListener('snapshot', reload);
    return () => stream.close();
  }, [id, reload]);
  return connection;
}
