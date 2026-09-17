import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, etagFor, uploadPdf, validatePdfSelection } from './api';
afterEach(() => vi.unstubAllGlobals());
describe('HTTP safety and concurrency contracts', () => {
  it('writes preserve If-Match and a stable idempotency key, with no authentication', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{"id":"d1","generation":4}', { headers: { ETag: '"4"' } }));
    vi.stubGlobal('fetch', fetcher);
    const result = await api('/documents/d1', { method: 'PATCH', body: { title: 'new' }, etag: '"3"', key: 'explicit-key' });
    const options = fetcher.mock.calls[0][1];
    expect(options.headers.get('If-Match')).toBe('"3"');
    expect(options.headers.get('Idempotency-Key')).toBe('explicit-key');
    expect(options.headers.has('Authorization')).toBe(false);
    expect(etagFor(result)).toBe('"4"');
  });
  it('keeps conflict evidence and never automatically retries a write', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'PRECONDITION_FAILED', message: 'changed', details: { current: 'server text' } }, request_id: 'req1' }), { status: 412 }));
    vi.stubGlobal('fetch', fetcher);
    await expect(api('/drafts/d1/segments/b1', { method: 'PATCH', body: {}, etag: '"1"' })).rejects.toMatchObject({ status: 412, code: 'PRECONDITION_FAILED', details: { current: 'server text' }, requestId: 'req1' });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('rejects arbitrary API URLs', async () => {
    await expect(api('https://example.com')).rejects.toBeInstanceOf(ApiError);
  });
});
describe('PDF-only intake', () => {
  it('keeps valid files when another file is invalid', () => {
    const files = [new File(['%PDF'], 'one.pdf', { type: 'application/pdf' }), new File(['text'], 'bad.txt', { type: 'text/plain' })];
    const result = validatePdfSelection(files, 50 * 1024 * 1024, 10);
    expect(result[0].error).toBeUndefined();
    expect(result[1].error).toContain('PDF');
  });
  it('rejects more than ten files without silently dropping them', () => {
    expect(() => validatePdfSelection(Array.from({ length: 11 }, () => new File(['x'], 'x.pdf')), 50, 10)).toThrow('10');
  });
  it('uses real chunk bytes and waits for verified inspector status before import', async () => {
    const calls: { path: string; options: RequestInit }[] = [];
    vi.stubGlobal('fetch', async (path: string, options: RequestInit) => {
      calls.push({ path, options });
      const result = path.endsWith('/uploads') ? { upload_id: 'u1', chunk_limit: 4 } : path.endsWith('/finalize') ? { status: 'inspecting' } : path === '/api/v1/uploads/u1' ? { upload_id: 'u1', status: 'verified', sha256: 'hash', page_count: 1 } : {};
      return new Response(JSON.stringify(result), { headers: { ETag: '"1"' } });
    });
    const progress: number[] = [];
    await uploadPdf(new File(['%PDF-1.7'], 'real.pdf', { type: 'application/pdf' }), p => progress.push(p.receivedBytes));
    expect(calls.filter(c => c.path.includes('/chunks/'))).toHaveLength(2);
    expect(calls.every(c => !c.path.endsWith('/imports'))).toBe(true);
    expect(progress.at(-1)).toBe(8);
    expect(new Headers(calls[1].options.headers).get('Content-Range')).toBe('bytes 0-3/8');
  });
});
