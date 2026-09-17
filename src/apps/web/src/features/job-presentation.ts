import { languageName } from '../languages';
import type { Job } from '../types';

const operations: Record<string, string> = {
  metadata_lookup: '查询文献信息', recovery: '恢复缺失内容', quality_check: '内容检查', maintenance: '维护实例', backup: '备份实例', restore: '恢复备份',
  provider_test: '测试 API 连接 / 密钥',
  inspect: '检查 PDF', inspecting: '检查 PDF', parse: '解析原文', parsing: '解析原文',
  translate: '全文翻译', translating: '全文翻译', candidate: '局部重译', semantic_review: '语义检查',
  export: '导出阅读版本', publish: '构建并发布', rebuild: '重建阅读版式', cleanup: '文档删除与文件清理',
  index: '更新检索索引', checking: '质量检查', building: '构建阅读版本', preflight: '结构预检', published: '发布阅读版本',
};
export function jobOperation(stage: string) { return operations[stage] ?? '后台任务'; }
export function jobName(job: Job) { return job.stage === 'provider_test' ? 'AI 服务连接测试' : job.stage === 'cleanup' ? '已删除文档' : job.title?.trim() || job.filename?.trim() || '未命名 PDF'; }
export function jobLocale(locale?: string | null) { return languageName(locale); }
export function jobTone(status: string) {
  if (['failed', 'outcome_unknown'].includes(status)) return 'error';
  if (['paused', 'waiting_config', 'waiting_configuration', 'waiting_budget', 'needs_review'].includes(status)) return 'attention';
  if (['pending', 'queued', 'running', 'translating', 'cancel_requested'].includes(status)) return 'active';
  return 'quiet';
}
export function jobProgress(job: Job) {
  const pages = ['inspect', 'inspecting', 'parse', 'parsing'].includes(job.stage);
  if (!pages && !['translate', 'translating', 'candidate', 'semantic_review'].includes(job.stage)) return null;
  const value = pages ? job.checked_pages : job.verified_blocks;
  const total = pages ? job.total_pages : job.total_blocks;
  if (value == null || total == null || !Number.isSafeInteger(value) || !Number.isSafeInteger(total) || total <= 0 || value < 0 || value > total) return null;
  return { value, total, label: pages ? `已检查 ${value} / ${total} 页` : `已完成 ${value} / ${total} 段` };
}

export function JobDateParts(value?: string) {
  const date = value ? new Date(value) : null;
  if (!date || !Number.isFinite(date.getTime())) return null;
  return { date: date.toLocaleDateString('zh-CN'), time: date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }), full: date.toLocaleString('zh-CN') };
}
