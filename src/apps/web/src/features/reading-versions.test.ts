import { describe, expect, it } from 'vitest';
import { readingVersions, readingVersionStatus } from './reading-versions';
import type { Document, History } from '../types';

const doc = { editions: [{ id: 'zh', target_locale: 'zh-Hans', current_artifact_id: 'current-old' }, { id: 'ja', target_locale: 'ja', current_artifact_id: 'current-ja' }] } as Document;
const artifact = (id: string, created_at?: string, locale = 'zh-Hans') => ({ id, created_at, locale, edition_id: locale === 'ja' ? 'ja' : 'zh', state: 'verified', template_id: 'reader-v13', source_revision_id: 'source', translation_revision_id: `translation-${id}` });

describe('reading versions', () => {
  it('pins each language current pointer, then sorts by date and a deterministic same-time key without mutating history', () => {
    const history: History = { artifacts: [artifact('z', '2026-10-16'), artifact('current-old', '2026-10-01'), artifact('a', '2026-10-16'), artifact('preview', '2026-10-17'), artifact('current-ja', '2026-10-10', 'ja')] };
    const original = structuredClone(history);
    expect(readingVersions(history, doc).map(version => version.id)).toEqual(['current-ja', 'current-old', 'preview', 'a', 'z']);
    expect(history).toEqual(original);
  });
  it('distinguishes unpublished resources from actual publication history without assuming verified means published', () => {
    const history: History = { artifacts: [], publications: [{ id: 'p', artifact_id: 'historical', operation: 'publish', generation: 1 }] };
    expect(readingVersionStatus(artifact('current-old'), history, doc)).toBe('当前阅读版');
    expect(readingVersionStatus(artifact('historical'), history, doc)).toBe('历史阅读版');
    expect(readingVersionStatus(artifact('preview'), history, doc)).toBe('未发布 · 可预览');
    expect(readingVersionStatus({ ...artifact('failed'), state: 'failed' }, history, doc)).toBe('生成失败');
  });
  it('keeps missing or malformed timestamps deterministic and allows an empty history', () => {
    const history: History = { artifacts: [artifact('z', 'not-a-date'), artifact('dated', '2026-10-01'), artifact('a')] };
    expect(readingVersions(history).map(version => version.id)).toEqual(['dated', 'a', 'z']);
    expect(readingVersions()).toEqual([]);
  });
});
