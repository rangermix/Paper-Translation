import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const base = { generation: 1, control_epoch: 1, task_role: 'main', title: '同名论文', document_id: 'doc', created_at: '2026-10-18T10:00:00Z' };
const jobs = [
  { ...base, id: 'prepare', stage: 'prepare_parser_model', status: 'failed', document_id: undefined, actual_model: { kind: 'none' }, error: { code: 'WORKER_FAILED', message: 'Worker failed' } },
  ...['upload', 'parse', 'translate', 'publish'].map((stage, index) => ({ ...base, id: stage, operation: stage, stage: stage === 'upload' ? 'inspect' : stage,
    status: stage === 'translate' ? 'outcome_unknown' : stage === 'parse' ? 'failed' : 'succeeded', parent_job_id: index ? ['upload', 'parse', 'translate'][index - 1] : null,
    actual_model: { kind: 'none' }, ...(stage === 'parse' ? { error: { code: 'PARSER_FAILED', message: 'Synthetic page failure', details: { page: 8 } }, import_id: 'source' } : {}),
    ...(stage === 'translate' ? { draft_id: 'draft', error: { code: 'OUTCOME_UNKNOWN', message: 'Synthetic unknown result' }, unknown_micro: null, cost_control_enabled: false,
      attempts: [{ id: 'unknown-attempt', status: 'outcome_unknown', request_id: 'provider-request' }] } : {}) })),
  { ...base, id: 'provider', stage: 'provider_test', status: 'succeeded', document_id: undefined, actual_model: { kind: 'api', model_id: 'synthetic-api-model' } },
];
async function fixture(page: Page) {
  const writes: { path: string; body: any }[] = [], queries: URLSearchParams[] = [], errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname.slice(7);
    if (request.method() !== 'GET') writes.push({ path, body: request.postDataJSON() });
    if (path.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: '' });
    if (path === '/jobs') {
      queries.push(url.searchParams);
      if (url.searchParams.has('parent_job_id')) return route.fulfill({ json: { items: [], next_cursor: null } });
      const stage = url.searchParams.get('stage'), next = url.searchParams.has('cursor');
      return route.fulfill({ json: { items: next ? [{ ...base, id: 'old', stage: 'parse', status: 'succeeded' }] : jobs.filter(job => !stage || job.stage === stage), next_cursor: next || stage ? null : 'provider' } });
    }
    const value = path === '/settings/preferences' ? { theme: 'light', generation: 1 } : path === '/jobs/paused'
      ? { ...base, id: 'paused', stage: 'translate', status: 'waiting_config', error: { code: 'PROVIDER_CONFIG', message: 'Synthetic missing config' } }
      : jobs.find(job => path === `/jobs/${job.id}`) ?? { items: [] };
    return route.fulfill({ json: value, headers: { ETag: '"1"' } });
  });
  return { writes, queries, errors };
}

test('task groups preserve every independent main task, server pagination and attention visibility', async ({ page }) => {
  const { writes, queries, errors } = await fixture(page);
  await page.goto('/#/jobs');
  const documents = page.getByRole('region', { name: /文档处理.*本页 4 项/ });
  const instance = page.getByRole('region', { name: /实例维护与服务.*本页 2 项/ });
  await expect(documents.locator('.job-entry')).toHaveCount(4);
  await expect(instance.locator('.job-entry')).toHaveCount(2);
  for (const id of ['upload', 'parse', 'translate', 'publish']) await expect(documents.locator(`a[href="#/jobs/${id}"]`)).toBeVisible();
  await expect(page.locator('.job-pagination')).toContainText('第 1 页 · 6 项任务');
  await expect(page.locator('.job-instance-attention')).toContainText('本页有 1 项');
  await page.getByRole('button', { name: '查看实例任务' }).click();
  await expect(page.locator('#instance-jobs-heading')).toBeFocused();
  await expect(instance.locator('a[href="#/jobs/prepare"] .job-info')).toHaveText('准备解析模型');
  await expect(instance.locator('a[href="#/jobs/prepare"]')).toContainText('后台处理失败');
  await expect(instance).not.toContainText('无需模型');
  await expect(instance).toContainText('synthetic-api-model');
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(page.locator('.job-pagination')).toContainText('第 2 页 · 1 项任务');
  await page.getByLabel('任务类型').selectOption('prepare_parser_model');
  await expect(page.locator('.job-pagination')).toContainText('第 1 页 · 1 项匹配任务');
  expect(queries.filter(query => !query.has('parent_job_id')).every(query => query.get('top_level_only') === 'true')).toBe(true);
  expect(queries.some(query => query.get('cursor') === 'provider')).toBe(true);
  expect(writes).toEqual([]); expect(errors).toEqual([]);
});

test('failures retain evidence before logs and only offer recovery destinations supported by the job', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { writes, errors } = await fixture(page);
  await page.goto('/#/jobs/parse');
  const failure = page.getByRole('alert', { name: '任务错误' });
  await expect(failure).toContainText('解析原文未完成');
  await expect(failure).toContainText('第 8 页');
  await expect(failure).toContainText('PARSER_FAILED');
  await expect(failure).toContainText('Synthetic page failure');
  await expect(failure.getByRole('link', { name: '查看解析设置' })).toHaveAttribute('href', '#/settings');
  await expect(failure.getByRole('link', { name: '查看解析结果' })).toHaveAttribute('href', '#/preflight/source');
  expect(await failure.evaluate(node => !!(node.compareDocumentPosition(document.querySelector('.job-records')!) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
  await expect(page.getByRole('button', { name: /恢复|重试/ })).toHaveCount(0);
  await page.screenshot({ path: outputDirectory('task-failure-390.png'), fullPage: true });
  await page.evaluate(() => { location.hash = '/jobs/prepare'; });
  await expect(failure).toContainText('后台处理失败，当前记录未说明具体原因。');
  await expect(failure).toContainText('Worker failed');
  await expect(failure).not.toContainText('第 8 页');
  await expect(failure).not.toContainText('显存');
  await expect(failure.getByRole('link', { name: '查看文档与已有结果' })).toHaveCount(0);
  await expect(page.locator('.job-detail h2')).toHaveText('准备解析模型');
  expect(writes).toEqual([]); expect(errors).toEqual([]);
});

test('unknown outcomes lead to reconciliation without resend, and risk acceptance remains explicit', async ({ page }) => {
  const { writes, errors } = await fixture(page);
  await page.goto('/#/jobs/translate');
  const failure = page.getByRole('alert', { name: '任务错误' });
  await expect(failure).toContainText('结果未确定前，不要直接重发请求');
  await expect(page.getByRole('button', { name: '恢复安全缺失单元' })).toHaveCount(0);
  await failure.getByRole('button', { name: '查看未知请求' }).click();
  const reconcile = page.getByRole('button', { name: '核对未知请求', exact: true });
  await expect(reconcile).toBeFocused();
  await reconcile.click();
  const dialog = page.getByRole('dialog', { name: '核对未知付费请求' });
  await expect(dialog.getByLabel('处理方式')).toHaveValue('record_evidence');
  await dialog.getByLabel('处理方式').selectOption('retry_accept_risk');
  await dialog.getByLabel('核对记录或操作理由').fill('Synthetic test evidence');
  await expect(dialog.getByRole('button', { name: '提交处理决定' })).toBeDisabled();
  expect(writes).toEqual([]);
  await dialog.getByRole('checkbox').check();
  await dialog.getByRole('button', { name: '提交处理决定' }).click();
  await expect(dialog).not.toBeVisible();
  expect(writes).toEqual([{ path: '/attempts/unknown-attempt/resolve', body: { decision: 'retry_accept_risk', reason: 'Synthetic test evidence', duplicate_charge_risk_confirmed: true } }]);
  expect(errors).toEqual([]);
});

test('safe resume remains scoped to an eligible paused task', async ({ page }) => {
  const { writes } = await fixture(page);
  await page.goto('/#/jobs/paused');
  const failure = page.getByRole('alert', { name: '任务错误' });
  await expect(failure).toContainText('它不会重发结果未知的请求');
  await expect(failure.getByRole('link', { name: '查看服务设置' })).toBeVisible();
  expect(writes).toEqual([]);
  await page.getByRole('button', { name: '恢复安全缺失单元' }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toEqual({ path: '/jobs/paused/resume', body: {} });
});
