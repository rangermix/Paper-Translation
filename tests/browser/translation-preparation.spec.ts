import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const profile = { generation: 1, configured: true, dispatch_configuration_ready: true, provider: 'openai',
  api_protocol: 'responses', auth_mode: 'bearer', endpoint: 'https://example.invalid/v1/responses',
  model_id: 'configured-translator', profile_revision: 'profile', profile_hash: 'b'.repeat(64),
  semantic_review_enabled: true, cost_control_enabled: false, currency: 'USD' };
const analyst = { id: 'minicpm5-1b-q4', label: 'MiniCPM5-1B Q4', model_id: `sha256:${'1'.repeat(64)}`,
  runtime: 'mlx', bits: 4, repo: 'synthetic/analyst', revision: 'a'.repeat(40),
  download_bytes: 618659840, status: 'not_downloaded' };
const estimates = {
  off: { additional_requests: 0, additional_cost_micro: 0, backend: 'none' },
  extractive: { additional_requests: 0, additional_cost_micro: 0, backend: 'deterministic' },
  provider: { additional_requests: 1, additional_cost_micro: 2500, backend: 'provider' },
  local: { additional_requests: 1, additional_cost_micro: null, backend: 'local' },
};
const pack = { revision: 'preparation-v1', source_revision_id: 'source', source_hash: 'a'.repeat(64), target_locale: 'zh-Hans',
  summary: [{ text: 'The paper distinguishes process rank from matrix rank.', evidence_ids: ['e1'] }],
  evidence: [{ id: 'e1', block_id: 'b1', quote: 'Process rank identifies a worker.', role: 'definition', scope: 'h1' }],
  headings: [{ block_id: 'h1', text: 'Distributed workers' }],
  concepts: [{ id: 'c1', source: 'rank', aliases: ['process rank'], scope: 'h1', evidence_ids: ['e1'],
    target: '进程序号', origin: 'model', method: 'definition', review_status: 'not_reviewed' }],
  coverage: { scanned_blocks: 12, omitted_evidence: 3, omitted_concepts: 2, oversized_passages: 1, model_saw_full_paper: false },
  warnings: ['PREPARATION_CONTEXT_LIMIT'], analysis: { profile: { model_id: analyst.model_id } },
};

async function setup(page: Page, localTranslator = false, summary = true,
  context = { mode: 'background_and_terms', omitted: 0 }) {
  const currentProfile = localTranslator ? { ...profile, provider: 'local', api_protocol: 'local_translation',
    model_id: 'configured-local-translator', endpoint: 'http://local-translator:8090/v1/completions', auth_mode: 'none' } : profile;
  const writes: { path: string; body: any }[] = [], reads: string[] = [], errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const source = { import_id: 'parsed', document_id: 'doc', generation: 1, preflight_generation: 1, status: 'ready',
    source_revision_id: 'source', source_hash: pack.source_hash, source_language: 'en', page_count: 1, block_count: 1,
    unresolved_blocks: 0, can_translate: true, profile_hash: currentProfile.profile_hash,
    blocks: [{ id: 'b1', kind: 'paragraph', normalized_text: pack.evidence[0].quote }], preparation_estimates: estimates };
  const document = { id: 'doc', generation: 1, title: 'Preparation contract', source_asset_id: 'asset',
    source_revision_id: 'source', lifecycle: 'active', tags: [], starred: false,
    editions: [{ id: 'edition', target_locale: 'zh-Hans' }] };
  const draft = { id: 'draft', generation: 1, document_id: 'doc', edition_id: 'edition', source_revision_id: 'source',
    source_hash: pack.source_hash, target_locale: 'zh-Hans', glossary_revision: 'glossary-v1', preparation_revision: pack.revision,
    source: { language: 'en', protected_atoms: {} }, segments: [{ block_id: 'b1', source_text: pack.evidence[0].quote,
      source_hash: 'c'.repeat(64), context_hash: 'd'.repeat(64), version: 1, review_status: 'unreviewed',
      target_inline: [{ type: 'text', text: '进程序号标识一个工作进程。' }] }] };
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname.slice(7);
    if (path.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: '' });
    if (request.method() === 'GET') reads.push(path + url.search);
    else if (!path.includes('/chunks/')) writes.push({ path, body: request.postDataJSON() });
    const values: Record<string, unknown> = {
      '/capabilities': { phase: 'M2', source_mime_types: ['application/pdf'] },
      '/settings/provider': currentProfile, '/settings/preferences': { generation: 1, locale: 'zh-Hans', theme: 'light' },
      '/settings/local-models': { models: [analyst] }, '/documents/doc': document, '/drafts/draft': draft,
      '/imports/parsed/preflight': source,
      '/imports/saved/preflight': { ...source, status: 'sealed', translation_targets: [{ draft_id: 'draft', target_locale: 'zh-Hans' }] },
      '/editions/edition/preflight': { ...source, locale: 'zh-Hans', profile: currentProfile },
      '/drafts/draft/translation-preflight': { ...source, locale: 'zh-Hans', profile: currentProfile },
      '/drafts/draft/preparation': { available: true, scope: 'draft', preparation: { ...pack, summary: summary ? pack.summary : [], analysis: summary ? pack.analysis : null, translation_context_mode: context.mode } },
      '/glossaries/effective': { revision: 'glossary-v1' }, '/imports': document,
      '/uploads': { upload_id: 'upload', status: 'created', chunk_limit: 4096, generation: 1 },
      '/uploads/upload/chunks/0': { upload_id: 'upload', status: 'uploading', generation: 2 },
      '/uploads/upload/finalize': { upload_id: 'upload', status: 'verified', generation: 3 },
      '/jobs/job': { id: 'job', generation: 1, stage: 'translate', status: 'running', control_epoch: 0,
        progress: { preparation_status: 'completed', preparation_requests: 1, preparation_terms: 3, preparation_warnings: ['PREPARATION_CONTEXT_LIMIT'],
          preparation_context_mode: context.mode, preparation_omitted_units: context.omitted } },
    };
    return route.fulfill({ json: values[path] ?? (request.method() === 'GET' ? { items: [] } : { job_id: 'job' }), headers: { ETag: '"1"' } });
  });
  return { writes, reads, errors, draft };
}

for (const flow of ['upload', 'preflight', 'edition', 'continue', 'candidate'] as const) {
  test(`${flow} sends the chosen preparation and resets consent when it changes`, async ({ page }) => {
    const { writes, reads, errors } = await setup(page);
    const routes = { upload: '/#/upload', preflight: '/#/preflight/parsed', edition: '/#/documents/doc',
      continue: '/#/preflight/saved', candidate: '/#/drafts/draft' };
    await page.goto(routes[flow]);
    if (flow === 'edition') await page.getByRole('button', { name: '确认此语言版翻译', exact: true }).click();
    if (flow === 'continue') await page.getByRole('button', { name: /开始翻译 ·/ }).click();
    if (flow === 'candidate') {
      await page.getByLabel('选择段落 b1', { exact: true }).check();
      await page.getByRole('button', { name: /局部重译/ }).click();
    }
    if (flow === 'upload') await page.locator('#pdf-files').setInputFiles({ name: 'test.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7 fixture') });
    const container = flow === 'upload' || flow === 'preflight' ? page : page.getByRole('dialog');
    const preparation = container.getByLabel('翻译前准备', { exact: true });
    await expect(preparation).toHaveValue('extractive');
    const consent = container.getByRole('checkbox', { name: /同意.*(?:必要|所选|上述)/ });
    await consent.check();
    await preparation.selectOption('local');
    await expect(consent).not.toBeChecked();
    const local = container.getByRole('region', { name: '本地分析模型', exact: true });
    await expect(local.getByText('MiniCPM5-1B Q4', { exact: true })).toBeVisible();
    await expect(local).toContainText('590 MiB');
    await expect.poll(() => reads.includes('/settings/local-models?purpose=analysis')).toBe(true);
    expect(writes).toEqual([]);
    await consent.check();
    const names = { upload: '上传并开始处理', preflight: '确认外发，开始翻译', edition: '确认外发，翻译此语言版',
      continue: '开始翻译未完成内容', candidate: '创建局部候选任务' };
    await container.getByRole('button', { name: names[flow], exact: true }).click();
    const paths = { upload: '/imports', preflight: '/imports/parsed/confirm', edition: '/editions/edition/translate',
      continue: '/drafts/draft/translate', candidate: '/drafts/draft/candidates' };
    await expect.poll(() => writes.some(row => row.path === paths[flow])).toBe(true);
    const body = writes.find(row => row.path === paths[flow])!.body;
    expect(flow === 'upload' ? body.workflow : body).toMatchObject({ preparation: { mode: 'local' }, external_processing_confirmed: true });
    expect(writes.some(row => row.path === '/settings/provider' || row.path.endsWith('/prepare'))).toBe(false);
    expect(errors).toEqual([]);
  });
}

test('local analyst preparation is explicit and does not replace the configured local translator', async ({ page }) => {
  const { writes } = await setup(page, true);
  await page.goto('/#/preflight/saved');
  await page.getByRole('button', { name: /开始翻译 ·/ }).click();
  const dialog = page.getByRole('dialog'), preparation = dialog.getByLabel('翻译前准备', { exact: true });
  await expect(preparation.locator('option[value="provider"]')).toBeDisabled();
  await preparation.selectOption('local');
  await expect(dialog.getByText('configured-local-translator', { exact: true })).toBeVisible();
  await expect(dialog.getByRole('region', { name: '本地分析模型' })).toContainText('MiniCPM5-1B Q4');
  expect(writes).toEqual([]);
  await dialog.getByRole('button', { name: '准备本地分析模型', exact: true }).click();
  await expect.poll(() => writes).toEqual([{ path: '/settings/local-models/minicpm5-1b-q4/prepare', body: {} }]);
});

test('provider analysis exposes an extra estimate and off mode is sent explicitly', async ({ page }) => {
  const { writes } = await setup(page);
  await page.goto('/#/preflight/parsed');
  const preparation = page.getByLabel('翻译前准备', { exact: true });
  await preparation.selectOption('provider');
  await expect(page.getByText(/额外分析请求：1 次/)).toBeVisible();
  await expect(page.getByText(/USD 0.002500/)).toBeVisible();
  await preparation.selectOption('off');
  await page.getByLabel(/同意将必要的源文/).check();
  await page.getByRole('button', { name: '确认外发，开始翻译' }).click();
  expect(writes[0].body.preparation).toEqual({ mode: 'off' });
});

test('semantic review keeps its own consent and does not submit translation preparation', async ({ page }) => {
  const { writes } = await setup(page);
  await page.goto('/#/drafts/draft');
  await page.getByLabel('选择段落 b1', { exact: true }).check();
  await page.getByRole('button', { name: '辅助语义评审', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('翻译前准备', { exact: true })).toHaveCount(0);
  await dialog.getByRole('checkbox').check();
  await dialog.getByRole('button', { name: '创建辅助语义评审任务', exact: true }).click();
  expect(writes[0].body).not.toHaveProperty('preparation');
});

for (const width of [1440, 390]) test(`frozen preparation evidence stays read-only and usable at ${width}px`, async ({ page }) => {
  const { writes, errors } = await setup(page);
  await page.setViewportSize({ width, height: 900 });
  await page.goto('/#/drafts/draft');
  await expect(page).toHaveTitle(/对照文库/);
  await expect(page.getByRole('heading', { name: '译文编辑', exact: true })).toBeVisible();
  await page.getByText('草稿基准准备与依据', { exact: true }).click();
  const view = page.getByRole('region', { name: '草稿基准准备与依据', exact: true });
  await expect(view.getByRole('heading', { name: '模型概述建议', exact: true })).toBeVisible();
  await expect(view).toContainText('未阅读全文');
  await expect(view).toContainText('Distributed workers');
  await expect(view).toContainText('进程序号');
  await expect(view).toContainText('未经人工核对');
  await expect(view.getByText(pack.evidence[0].quote, { exact: true }).first()).toBeVisible();
  await expect(view.getByRole('link', { name: '管理术语表', exact: true })).toHaveAttribute('href', '#/glossary');
  await expect(page.getByRole('button', { name: '封存当前修订', exact: true })).toBeEnabled();
  expect(writes).toEqual([]);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  if (width === 390) {
    const scopeCell = await view.getByRole('cell').nth(2).boundingBox();
    expect(scopeCell!.x + scopeCell!.width).toBeLessThanOrEqual(width);
  }
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: outputDirectory(`preparation-evidence-${width}.png`), fullPage: true });
  expect(errors).toEqual([]);
});

for (const width of [1440, 390]) test(`local preparation controls remain readable at ${width}px`, async ({ page }) => {
  const { errors, writes } = await setup(page);
  await page.setViewportSize({ width, height: 900 });
  await page.goto('/#/preflight/saved');
  await page.getByRole('button', { name: /开始翻译 ·/ }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('翻译前准备', { exact: true }).selectOption('local');
  await expect(dialog.getByText('MiniCPM5-1B Q4', { exact: true })).toBeVisible();
  await dialog.getByRole('region', { name: '本地分析模型', exact: true }).scrollIntoViewIfNeeded();
  expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  await page.screenshot({ path: outputDirectory(`preparation-controls-${width}.png`) });
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test('extractive preparation labels source excerpts without claiming a generated summary', async ({ page }) => {
  await setup(page, false, false);
  await page.goto('/#/drafts/draft');
  await page.getByText('草稿基准准备与依据', { exact: true }).click();
  const view = page.getByRole('region', { name: '草稿基准准备与依据' });
  await expect(view.getByRole('heading', { name: '来源摘录概览', exact: true })).toBeVisible();
  await expect(view.getByRole('heading', { name: '模型概述建议', exact: true })).toHaveCount(0);
});

test('job progress separates preparation from translated segments', async ({ page }) => {
  await setup(page);
  await page.goto('/#/jobs/job');
  const progress = page.getByRole('region', { name: '翻译准备进度', exact: true });
  await expect(progress).toContainText('准备已完成');
  await expect(progress).toContainText('译名建议：3');
  await expect(progress).toContainText('分析请求：1');
  await expect(progress).toContainText('提示：1');
});

test('terminology-only translators disclose the context limit in saved preparation and progress', async ({ page }) => {
  await setup(page, true, true, { mode: 'terms_only', omitted: 2 });
  await page.goto('/#/drafts/draft');
  await page.getByText('草稿基准准备与依据', { exact: true }).click();
  await expect(page.getByRole('region', { name: '草稿基准准备与依据', exact: true })).toContainText('当前翻译模型仅使用准备的术语');
  await page.goto('/#/jobs/job');
  const progress = page.getByRole('region', { name: '翻译准备进度', exact: true });
  await expect(progress).toContainText('当前翻译模型仅使用准备的术语');
  await expect(progress).toContainText('2 个翻译单元未携带论文级上下文');
});

for (const width of [1440, 390]) test(`segment and candidate inspectors use their own preparation at ${width}px`, async ({ page }) => {
  const { draft, writes, errors } = await setup(page);
  await page.setViewportSize({ width, height: 900 });
  const reads: string[] = [];
  const candidate = { id: 'candidate', status: 'ready', generation: 1, job_id: 'job',
    base: { source_revision_id: draft.source_revision_id, source_hash: draft.source_hash,
      glossary_revision: draft.glossary_revision, requested_glossary_revision: draft.glossary_revision,
      segments: { b1: { version: 1, source_hash: 'c'.repeat(64), context_hash: 'd'.repeat(64), reviewed: false } } },
    results: { b1: [{ type: 'text', text: '待选择的候选译文。' }] } };
  await page.route('**/api/v1/drafts/draft', route => route.fulfill({ json: { ...draft, candidates: [candidate] } }));
  await page.route('**/api/v1/drafts/draft/preparation*', route => {
    const url = new URL(route.request().url());
    reads.push(url.search);
    const scope = url.searchParams.has('block_id') ? 'segment' : url.searchParams.has('candidate_id') ? 'candidate' : 'draft';
    const revision = scope === 'segment' ? 'accepted-segment-preparation' : scope === 'candidate' ? 'candidate-preparation' : pack.revision;
    return route.fulfill({ json: { available: true, scope, preparation: { ...pack, revision } } });
  });
  await page.goto('/#/drafts/draft');
  await page.getByText('草稿基准准备与依据', { exact: true }).click();
  const baseline = page.getByRole('region', { name: '草稿基准准备与依据', exact: true });
  await expect(baseline).toContainText(pack.revision);
  await expect(baseline).toContainText('已有段落和候选可能使用其他准备');
  await page.getByRole('button', { name: '展开段落 b1', exact: true }).click();
  await page.getByText('本段翻译准备与依据', { exact: true }).click();
  const segment = page.getByRole('region', { name: '段落 b1 的翻译准备与依据', exact: true });
  await expect(segment).toContainText('accepted-segment-preparation');
  await expect(segment).not.toContainText(pack.revision);
  await page.getByText('此候选的翻译准备与依据', { exact: true }).click();
  const candidateView = page.getByRole('region', { name: '候选 candidate 的翻译准备与依据', exact: true });
  await expect(candidateView).toContainText('candidate-preparation');
  await expect(candidateView).not.toContainText('accepted-segment-preparation');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await candidateView.screenshot({ path: outputDirectory(`preparation-candidate-${width}.png`) });
  expect(reads).toContain('');
  expect(reads).toContain('?block_id=b1');
  expect(reads).toContain('?candidate_id=candidate');
  expect(reads.every(query => !(query.includes('block_id') && query.includes('candidate_id')))).toBe(true);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test('a segment without preparation never inherits the visible draft baseline', async ({ page }) => {
  const { writes, errors } = await setup(page);
  await page.route('**/api/v1/drafts/draft/preparation?block_id=b1', route => route.fulfill({ json: {
    available: false, scope: 'segment', preparation: null,
  } }));
  await page.goto('/#/drafts/draft');
  await page.getByText('草稿基准准备与依据', { exact: true }).click();
  await expect(page.getByRole('region', { name: '草稿基准准备与依据', exact: true })).toContainText(pack.revision);
  await page.getByRole('button', { name: '展开段落 b1', exact: true }).click();
  await page.getByText('本段翻译准备与依据', { exact: true }).click();
  const segment = page.getByRole('region', { name: '段落 b1 的翻译准备与依据', exact: true });
  await expect(segment).toContainText('本段没有已保存的准备记录');
  await expect(segment).not.toContainText(pack.revision);
  await expect(segment.getByRole('heading', { name: '模型概述建议', exact: true })).toHaveCount(0);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});
