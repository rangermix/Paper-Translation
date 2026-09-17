import type { Upload, Versioned } from './types';
const etags = new WeakMap<object, string>();
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown, public requestId?: string) { super(message); }
}
type Options = { method?: string; body?: unknown; etag?: string; key?: string; headers?: HeadersInit; signal?: AbortSignal };
export function etagFor(value: unknown): string | undefined {
  if (!value || typeof value !== 'object') return undefined;
  return etags.get(value) ?? ((value as Versioned).generation !== undefined ? `"${(value as Versioned).generation}"` : undefined);
}
export async function api<T = Record<string, unknown>>(path: string, options: Options = {}): Promise<T> {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('://')) throw new ApiError(0, 'INVALID_PATH', '请求路径无效');
  const method = options.method ?? 'GET';
  const headers = new Headers(options.headers);
  const mutation = !['GET', 'HEAD'].includes(method);
  if (mutation) { headers.set('X-Library-Request', '1'); headers.set('Idempotency-Key', options.key ?? crypto.randomUUID()); }
  if (options.etag) headers.set('If-Match', options.etag);
  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    if (options.body instanceof Blob || options.body instanceof ArrayBuffer || ArrayBuffer.isView(options.body)) body = options.body as BodyInit;
    else { headers.set('Content-Type', 'application/json'); body = JSON.stringify(options.body); }
  }
  let response: Response;
  try { response = await fetch(`/api/v1${path}`, { method, headers, body, signal: options.signal, credentials: 'same-origin', cache: 'no-store' }); }
  catch (error) { if (error instanceof DOMException && error.name === 'AbortError') throw error; throw new ApiError(0, 'NETWORK_UNAVAILABLE', mutation ? '请求连接中断，操作结果尚不确定。请刷新服务端状态后再决定是否重试。' : '无法连接服务，请检查服务状态后重试。'); }
  const text = await response.text();
  let data: unknown;
  try { data = text ? JSON.parse(text) : {}; } catch { throw new ApiError(response.status, 'INVALID_RESPONSE', '服务返回了无法读取的响应'); }
  if (!response.ok) {
    const payload = data as { error?: { code?: string; message?: string; details?: unknown }; request_id?: string };
    throw new ApiError(response.status, payload.error?.code ?? `HTTP_${response.status}`, payload.error?.message ?? '操作失败', payload.error?.details, payload.request_id);
  }
  if (data && typeof data === 'object' && response.headers.has('ETag')) etags.set(data, response.headers.get('ETag')!);
  return data as T;
}
export function validatePdfSelection(files: File[], maxBytes: number, maxBatch: number) {
  if (files.length > maxBatch) throw new Error(`一次最多选择 ${maxBatch} 份 PDF，请减少文件数量。`);
  return files.map(file => ({ file, error: !/\.pdf$/i.test(file.name) || (file.type && file.type !== 'application/pdf') ? '只接受 PDF 文件。' : file.size === 0 ? '文件为空。' : file.size > maxBytes ? `文件超过 ${Math.floor(maxBytes / 1024 / 1024)} MiB 限制。` : undefined }));
}
async function sha256(bytes: ArrayBuffer) { return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), x => x.toString(16).padStart(2, '0')).join(''); }
export type UploadProgress = { receivedBytes: number; totalBytes: number; status: string; uploadId?: string };
export async function uploadPdf(file: File, onProgress: (progress: UploadProgress) => void, signal?: AbortSignal): Promise<Upload> {
  const upload = await api<Upload>('/uploads', { method: 'POST', body: { filename: file.name, media_type: 'application/pdf', byte_size: file.size }, signal });
  const chunkLimit = Math.min(upload.chunk_limit ?? 4 * 1024 * 1024, 4 * 1024 * 1024);
  if (chunkLimit <= 0) throw new ApiError(0, 'INVALID_UPLOAD_CONFIG', '服务返回了无效分块限制');
  const wholeBytes = await file.arrayBuffer();
  const hash = await sha256(wholeBytes);
  let current: Upload = upload;
  for (let offset = 0, index = 0; offset < file.size; index++) {
    const end = Math.min(offset + chunkLimit, file.size);
    const bytes = wholeBytes.slice(offset, end);
    current = await api<Upload>(`/uploads/${upload.upload_id}/chunks/${index}`, { method: 'PUT', body: bytes, etag: etagFor(current), headers: { 'Content-Type': 'application/octet-stream', 'Content-Range': `bytes ${offset}-${end - 1}/${file.size}`, 'X-Chunk-SHA256': await sha256(bytes) }, signal });
    offset = end;
    onProgress({ receivedBytes: current.received_bytes ?? end, totalBytes: file.size, status: 'uploading', uploadId: upload.upload_id });
  }
  current = await api<Upload>(`/uploads/${upload.upload_id}/finalize`, { method: 'POST', body: { expected_sha256: hash, total_bytes: file.size }, etag: etagFor(current), signal });
  onProgress({ receivedBytes: file.size, totalBytes: file.size, status: 'inspecting', uploadId: upload.upload_id });
  const started = Date.now();
  while (current.status !== 'verified') {
    if (['failed', 'rejected', 'expired', 'cancelled'].includes(current.status)) throw new ApiError(422, current.error?.code ?? 'PDF_INVALID', current.error?.message ?? 'PDF 检查失败，原件尚未入库。');
    if (Date.now() - started > 20 * 60 * 1000) throw new ApiError(0, 'INSPECTION_PENDING', `原件检查仍在后台处理，可在任务中心查看上传 ${upload.upload_id}。`);
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    current = await api<Upload>(`/uploads/${upload.upload_id}`, { signal });
    if (current.status !== 'verified') await new Promise(resolve => setTimeout(resolve, 1500));
  }
  return { ...current, duplicate_documents: current.duplicate_documents ?? current.duplicates, upload_id: upload.upload_id };
}
