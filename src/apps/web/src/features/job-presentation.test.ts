import { describe, expect, it } from 'vitest';
import { jobName, jobOperation, jobProgress } from './job-presentation';
import type { Job } from '../types';

const job = (patch: Partial<Job> = {}): Job => ({ id: 'job_opaque', stage: 'inspect', status: 'running', control_epoch: 0, ...patch });
describe('job presentation', () => {
  it('uses readable PDF context and localized operation names', () => {
    expect(jobName(job({ title: 'Pathways' }))).toBe('Pathways');
    expect(jobName(job({ filename: '研究.pdf' }))).toBe('研究.pdf');
    expect(jobName(job())).toBe('未命名 PDF');
    expect(jobName(job({ stage: 'cleanup', title: 'Deleted private title' }))).toBe('已删除文档');
    expect(jobOperation('inspect')).toBe('检查 PDF');
    expect(jobOperation('export')).toBe('导出阅读版本');
  });
  it('counts verified blocks separately from request and unit counts', () => {
    expect(jobProgress(job({ stage: 'translate', verified_blocks: 3, total_blocks: 12, verified_units: 8, total_units: 20, request_count: 15 })))
      .toEqual({ value: 3, total: 12, label: '已完成 3 / 12 段' });
    expect(jobProgress(job({ checked_pages: 2, total_pages: 4 })))
      .toEqual({ value: 2, total: 4, label: '已检查 2 / 4 页' });
  });
  it('does not invent progress from status, requests, missing totals or invalid counts', () => {
    expect(jobProgress(job({ status: 'succeeded' }))).toBeNull();
    expect(jobProgress(job({ stage: 'translate', request_count: 50, total_blocks: 10 }))).toBeNull();
    expect(jobProgress(job({ checked_pages: 0, total_pages: 0 }))).toBeNull();
    expect(jobProgress(job({ checked_pages: 5, total_pages: 4 }))).toBeNull();
    expect(jobProgress(job({ stage: 'export', verified_blocks: 10, total_blocks: 10 }))).toBeNull();
  });
});
