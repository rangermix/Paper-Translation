import { t, getUiLocale } from '../i18n';
import type { Document, History } from '../types';

export type ReadingVersion = History['artifacts'][number];
export function versionTime(value?: string) {
  if (!value) return t("时间未记录");
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? t("时间未记录") : date.toLocaleString(getUiLocale());
}

export function readingVersions(history?: History, document?: Document): ReadingVersion[] {
  const current = new Set(document?.editions.flatMap(edition => edition.current_artifact_id ? [edition.current_artifact_id] : []));
  const timestamp = (value?: string) => value && Number.isFinite(Date.parse(value)) ? Date.parse(value) : 0;
  return (history?.artifacts ?? []).map(artifact => ({ ...artifact,
    locale: artifact.locale ?? document?.editions.find(edition => edition.id === artifact.edition_id)?.target_locale ?? 'und',
    source_revision_id: artifact.source_revision_id ?? history?.translations?.find(revision => revision.id === artifact.translation_revision_id)?.source_revision_id ?? '',
  })).sort((left, right) => Number(current.has(right.id)) - Number(current.has(left.id))
    || timestamp(right.created_at) - timestamp(left.created_at) || left.id.localeCompare(right.id));
}

export function readingVersionStatus(version: ReadingVersion, history?: History, document?: Document) {
  if (document?.editions.some(edition => edition.current_artifact_id === version.id)) return t("当前阅读版");
  if (version.state && version.state !== 'verified') return version.state === 'failed' ? t("生成失败") : t("正在准备");
  const published = [...(history?.publications ?? []), ...(history?.publication_events ?? [])].some(event => event.artifact_id === version.id);
  return published ? t("历史阅读版") : t("未发布 · 可预览");
}
