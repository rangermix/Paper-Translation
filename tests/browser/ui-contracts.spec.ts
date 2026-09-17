import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory, outputPath } from './paths';
import { resolve } from 'node:path';
const evidence = process.env.LIBRARY_UI_EVIDENCE ? outputPath(process.env.LIBRARY_UI_EVIDENCE) : outputDirectory('ui-contracts');
const doc = { id: 'doc_contract', title: 'A study of reliable translation', tags: ['Systems'], starred: false, lifecycle: 'active', generation: 1, source_asset_id: 'asset_contract', source_revision_id: 'source_contract', page_count: 2, sha256: 'a'.repeat(64), byte_size: 3000, editions: [] };
const provider = { configured: false, provider: 'OpenAI', model_id: 'configured-model', profile_revision: 'profile-contract-v1', profile_hash: 'f'.repeat(64), parser_profile_revision: 'docling-v1', privacy_revision: 'privacy-v1', price_revision: 'price-v1', currency: 'USD', locale_matrix: [{ source: 'en', target: 'zh-Hans', enabled: true, status: 'test-only' }] };

for (const state of ['current-legacy', 'source-only', 'historical-legacy'] as const) {
  test(`legacy source location notice requires an explicitly current legacy artifact: ${state}`, async ({ page }) => {
    const currentId = state === 'current-legacy' ? 'legacy_current' : 'structured_current';
    const editions = state === 'source-only' ? [] : [{ id: 'edition_contract', target_locale: 'zh-Hans', current_artifact_id: currentId }];
    const paths: string[] = [];
    page.on('request', request => paths.push(new URL(request.url()).pathname));
    await mock(page, {
      '/documents/doc_contract': { ...doc, source_revision_id: undefined, editions },
      '/documents/doc_contract/history': { artifacts: [{ id: 'legacy_current', legacy: true }, { id: 'structured_current', legacy: false }] },
      '/reading-position': { generation: 0, block_id: null },
    });
    await page.goto('/#/documents/doc_contract');
    await expect(page.getByRole('link', { name: '打开原 PDF', exact: true })).toHaveAttribute('href', '/api/v1/documents/doc_contract/original');
    if (state === 'current-legacy') {
      await expect(page.getByRole('region', { name: '旧版来源定位说明' })).toContainText('无精确定位');
      await expect(page.getByRole('region', { name: '旧版来源定位说明' })).toContainText('没有可靠的逐块坐标');
    } else {
      await expect(page.getByRole('region', { name: '旧版来源定位说明' })).toHaveCount(0);
    }
    await expect(page.locator('.bbox')).toHaveCount(0);
    if (state === 'source-only') expect(paths).not.toContain('/api/v1/documents/doc_contract/history');
  });
}

test('semantic risk issues show their own exact source and target quotes as text, including empty quotes', async ({ page }) => {
  const source = 'Do not send </script><script>window.ATTACK_RAN=true</script> again.';
  const target = '不要再次发送 <img onerror="window.ATTACK_RAN=true"> 😀𠮷';
  const job = { id: 'quote_job', status: 'needs_review', stage: 'semantic_review', control_epoch: 0, generation: 1,
    issues: [{ rule: 'negation', severity: 'high', source_quote: source, target_quote: target, message: 'Compare the actual quoted condition.' },
      { rule: 'empty_quote', severity: 'high', source_quote: '', target_quote: '', message: 'Empty evidence stays empty.' }] };
  await mock(page, { '/jobs': { items: [job] }, '/jobs/quote_job': job });
  await page.goto('/#/jobs/quote_job');
  const issue = page.locator('.issue').filter({ hasText: 'negation' });
  await expect(issue.getByLabel('原文摘录', { exact: true })).toHaveText(source);
  await expect(issue.getByLabel('译文摘录', { exact: true })).toHaveText(target);
  const empty = page.locator('.issue').filter({ hasText: 'empty_quote' });
  await expect(empty.getByLabel('原文摘录', { exact: true })).toHaveText('');
  await expect(empty.getByLabel('译文摘录', { exact: true })).toHaveText('');
  await expect(issue.locator('script, img, [onerror]')).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as Record<string, unknown>).ATTACK_RAN)).toBeUndefined();
});
async function mock(page: Page, overrides: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    '/capabilities': { phase: 'M2', source_mime_types: ['application/pdf'], limits: { max_pdf_bytes: 52428800, max_batch_files: 10, max_pages: 200 } },
    '/settings/provider': provider,
    '/settings/preferences': { generation: 1, locale: 'zh-Hans', publish_policy: 'manual_approval', theme: 'light' },
    '/documents': { items: [doc], next_cursor: null },
    '/documents/doc_contract': doc,
    '/jobs': { items: [], next_cursor: null },
    '/glossaries': { items: [], next_cursor: null },
    '/translation-memory': { items: [], next_cursor: null },
    '/templates': { items: [{ id: 'reader-v1' }], next_cursor: null },
    ...overrides,
  };
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname.slice('/api/v1'.length);
    if (path.endsWith('/events')) return route.abort();
    const response = routes[path];
    if (response === undefined) return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { code: 'CONTRACT_ROUTE_MISSING', message: path } }) });
    return route.fulfill({ status: 200, contentType: 'application/json', headers: { ETag: '"1"' }, body: JSON.stringify(response) });
  });
}

test('old draft and new preflight always use their own revision-bound original PDF and page image',async({page})=>{
 const originalBase='/api/v1/documents/doc_contract/original',pageBase='/api/v1/documents/doc_contract/pages/1.png',oldQuery='?source_revision_id=source_old',newQuery='?source_draft_id=import_new';
 const loc={page:1,bbox:[10,20,90,40],page_size:[100,200],page_image_url:pageBase+oldQuery};
 const draft={id:'old',document_id:doc.id,edition_id:'edition',source_revision_id:'source_old',source_hash:'a'.repeat(64),generation:2,target_locale:'zh-Hans',original_url:originalBase+oldQuery,segments:[{block_id:'p',source_text:'Frozen original old source',target_inline:[{type:'text',text:'旧源译文'}],version:1,review_status:'unreviewed',locators:[loc]}]};
 const preflight={import_id:'import_new',document_id:doc.id,source_revision_id:'source_new',source_hash:'b'.repeat(64),generation:1,status:'ready',source_language:'en',page_count:1,block_count:1,unresolved_blocks:0,original_url:originalBase+newQuery,blocks:[{id:'newp',kind:'paragraph',normalized_text:'New replacement source',locators:[{...loc,page_image_url:pageBase+newQuery}]}]};
 await mock(page,{'/drafts/old':draft,'/imports/import_new/preflight':preflight});await page.route('**/api/v1/documents/doc_contract/pages/**',async route=>route.fulfill({status:200,contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2l9sAAAAASUVORK5CYII=','base64')}));
 await page.goto('/#/drafts/old');await page.getByRole('button',{name:'展开段落 p',exact:true}).click();await page.getByRole('button',{name:'对照原 PDF',exact:true}).click();await expect(page.getByRole('link',{name:'打开原页',exact:true})).toHaveAttribute('href',originalBase+oldQuery+'#page=1');await expect(page.getByRole('img',{name:'原 PDF 第 1 页',exact:true})).toHaveAttribute('src',pageBase+oldQuery);
 await page.goto('/#/preflight/import_new');await expect(page.getByRole('link',{name:'打开原页',exact:true})).toHaveAttribute('href',originalBase+newQuery+'#page=1');await expect(page.getByRole('img',{name:'原 PDF 第 1 页',exact:true})).toHaveAttribute('src',pageBase+newQuery);
});

test('cross-column continuation preserves a list item through a separately reviewed source operation',async({page})=>{
 const bbox=[10,150,90,159],pageHash='e'.repeat(64),pageSize=[100,200],raw='Input and output types, and the shapes of any in';
 const preflight={import_id:'continuation',document_id:doc.id,source_hash:'a'.repeat(64),generation:1,source_language:'en',status:'ready',unresolved_blocks:0,unresolved:[],page_count:1,block_count:2,blocks:[{id:'first',kind:'list_item',normalized_text:raw,provenance:[{page:1,bbox,page_size:pageSize}]},{id:'second',kind:'paragraph',normalized_text:'put/output tensors are known.',provenance:[{page:1,bbox:[10,20,90,40],page_size:pageSize}]}]};
 await mock(page,{'/imports/continuation/preflight':preflight,'/imports/continuation/native-regions':{generation:1,pages:[{page:1,page_size:pageSize,page_image_sha256:pageHash,text_regions:[{text:raw+'\u0002',bbox}]}],blocks:[{block_id:'first',native_text:raw+'\u0002',native_regions:[{page:1,page_size:pageSize,text:raw+'\u0002',bbox}]}]},'/imports/continuation/corrections':{id:'next'}});
 await page.goto('/#/preflight/continuation');await page.getByRole('button',{name:'查看原文与调整解析'}).click();await page.getByLabel('查看全部原生区域（含已覆盖）').check();await page.getByLabel('修正方式',{exact:true}).selectOption('continuation');await expect(page.getByLabel('继续本段的相邻来源块')).toHaveValue('second');await page.getByLabel('连接方式',{exact:true}).selectOption('');await page.getByLabel('原件核对记录与理由').fill('Original column-end in- continues as put/output in the next column, under the same bullet.');await expect(page.getByRole('button',{name:'创建新来源草稿并重检覆盖'})).toBeDisabled();await page.getByLabel(/我已对照原页，确认这两个相邻块/).check();await page.screenshot({path:resolve(evidence,'source-continuation-form.png'),fullPage:true});const sent=page.waitForRequest(r=>r.url().endsWith('/imports/continuation/corrections'));await page.getByRole('button',{name:'创建新来源草稿并重检覆盖'}).click();const request=await sent;expect(request.postDataJSON().operations).toEqual([{kind:'merge_continuation',block_ids:['first','second'],joiner:'',page_image_sha256:pageHash,visual_review_confirmed:true}]);expect(request.postDataJSON().evidence.quote).toBe(raw+'\u0002');
});

test('covered native footnote marker can be linked with explicit Unicode offsets and original page evidence',async({page})=>{
 const bbox=[10,20,15,28], pageHash='f'.repeat(64), locator={page:1,bbox:[0,0,100,40],page_size:[100,200]};
 const preflight={import_id:'footnote',document_id:doc.id,source_hash:'a'.repeat(64),generation:4,preflight_generation:4,source_revision_id:'s',source_language:'en',status:'ready',unresolved_blocks:0,unresolved:[],page_count:1,block_count:2,blocks:[{id:'p',kind:'paragraph',normalized_text:'😀 Claim 1.',provenance:[locator]},{id:'f',kind:'footnote',normalized_text:'1 Source note.',provenance:[{...locator,bbox:[0,150,100,180]}]}]};
 await mock(page,{'/imports/footnote/preflight':preflight,'/imports/footnote/native-regions':{generation:4,pages:[{page:1,page_size:[100,200],page_image_sha256:pageHash,text_regions:[{text:'1',bbox}]}],blocks:[{block_id:'p',native_text:'😀 Claim 1.',native_regions:[{page:1,page_size:[100,200],text:'1',bbox}]}]},'/imports/footnote/corrections':{id:'next'}});
 await page.route('**/api/v1/imports/footnote/preflight',route=>route.fulfill({status:200,contentType:'application/json',headers:{ETag:'"4"'},body:JSON.stringify(preflight)}));
 await page.goto('/#/preflight/footnote');await page.getByRole('button',{name:'查看原文与调整解析'}).click();await page.getByLabel('查看全部原生区域（含已覆盖）').check();await page.getByLabel('修正方式',{exact:true}).selectOption('footnote');await page.getByLabel('标记起点（Unicode 字符）').fill('8');await page.getByLabel('标记终点（不含此字符）').fill('9');await page.getByLabel('同页目标脚注').selectOption('f');await page.getByLabel('原件核对记录与理由').fill('Original page marker 1 refers to the matching same-page source footnote.');await page.getByLabel(/我已对照原页，确认所选标记/).check();const sent=page.waitForRequest(r=>r.url().endsWith('/imports/footnote/corrections'));await page.getByRole('button',{name:'创建新来源草稿并重检覆盖'}).click();const request=await sent;expect(request.headers()['if-match']).toBe('"4"');expect(request.postDataJSON().operations).toEqual([{kind:'annotate_footnote',block_id:'p',start:8,end:9,target_block_id:'f',page_image_sha256:pageHash,visual_review_confirmed:true}]);expect(request.postDataJSON().evidence).toEqual({page:1,bbox,quote:'1'});
});

test('reading position from an older artifact is explained and only an explicit current block selection writes', async ({ page }) => {
  const position = { generation: 0, document_id: doc.id, locale: 'zh-Hans', artifact_id: 'artifact_current', block_id: null, offset: 0, current_artifact: true, current_artifact_id: 'artifact_current', migration_required: true, migration_notice: 'Choose a block in the current version explicitly; no automatic jump was applied.', previous_position: { artifact_id: 'artifact_old', block_id: 'old-paragraph', offset: 17 } };
  await mock(page, {
    '/documents/doc_contract': { ...doc, editions: [{ id: 'edition_contract', target_locale: 'zh-Hans', generation: 3, current_artifact_id: 'artifact_current', draft_id: 'draft_contract' }] },
    '/reading-position': position,
    '/search': { items: [{ document_id: doc.id, document_title: doc.title, locale: 'zh-Hans', artifact_id: 'artifact_current', block_id: 'current-paragraph', source_text: 'A verified source paragraph', target_text: '已核实原文段落' }] },
  });
  const writes: unknown[] = [];
  await page.route('**/api/v1/reading-position*', route => {
    if (route.request().method() === 'PUT') writes.push({ body: route.request().postDataJSON(), etag: route.request().headers()['if-match'] });
    return route.fulfill({ contentType: 'application/json', headers: { ETag: '"0"' }, body: JSON.stringify(position) });
  });
  await page.goto('/#/documents/doc_contract');
  await expect(page.getByText('阅读位置属于另一个版本', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '查看旧版阅读位置' })).toHaveAttribute('href', '/artifacts/artifact_old/index.html#b-old-paragraph');
  await expect(page.getByRole('link', { name: '阅读当前版', exact: true })).toHaveAttribute('href', '/artifacts/artifact_current/index.html');
  expect(writes).toEqual([]);
  await page.screenshot({ path: `${evidence}/reading-position-migration.png`, fullPage: true });
  await page.goto('/#/search');
  await page.getByLabel('正文搜索', { exact: true }).fill('verified');
  await page.getByRole('button', { name: '搜索正文', exact: true }).click();
  await expect(page.getByText('A verified source paragraph', { exact: true })).toBeVisible();
  expect(writes).toEqual([]);
  const put = page.waitForRequest(r => r.url().includes('/reading-position') && r.method() === 'PUT');
  await page.getByRole('link', { name: '定位到固定版本中的段落', exact: true }).click();
  await put;
  await expect.poll(() => writes).toEqual([{ body: { document_id: doc.id, locale: 'zh-Hans', artifact_id: 'artifact_current', block_id: 'current-paragraph', offset: 0 }, etag: '"0"' }]);
  await expect(page.getByText('阅读位置属于另一个版本', { exact: true })).toBeVisible();
});

test('PDF intake retains valid selections and blocks non-PDF independently', async ({ page }) => {
  await mock(page);
  await page.goto('/#/upload');
  await page.locator('input[type=file]').setInputFiles([{ name: 'paper.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7') }, { name: 'bad.txt', mimeType: 'text/plain', buffer: Buffer.from('not a PDF') }]);
  await expect(page.getByText('只接受 PDF 文件。')).toBeVisible();
  await expect(page.getByText('paper.pdf', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '上传并开始处理', exact: true })).toBeEnabled();
  expect(await page.locator('input[type=file]').getAttribute('accept')).toBe('application/pdf,.pdf');
  await page.screenshot({ path: `${evidence}/upload-desktop.png`, fullPage: true });
});

test('unknown paid result never exposes ordinary resume or auto-retry', async ({ page }) => {
  const job = { id: 'job_unknown', title: 'Unknown request evidence', status: 'outcome_unknown', stage: 'translating', generation: 1, control_epoch: 2, actual_micro: 100, reserved_micro: 0, unknown_micro: 200, verified_blocks: 3, total_blocks: 8, verified_units: 4, total_units: 10, attempts: [{ id: 'attempt_unknown', status: 'outcome_unknown', request_id: 'request-evidence' }] };
  await mock(page, { '/jobs': { items: [job] }, '/jobs/job_unknown': job, '/attempts/attempt_unknown/resolve': job });
  let writes = 0;
  page.on('request', request => { if (request.method() === 'POST') writes++; });
  await page.goto('/#/jobs/job_unknown');
  await expect(page.getByText('请求结果未知，可能已经计费', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '恢复安全缺失单元' })).toHaveCount(0);
  await page.getByRole('button', { name: '核对未知请求' }).click();
  await page.getByLabel('处理方式').selectOption('retry_accept_risk');
  await expect(page.getByRole('button', { name: '提交处理决定' })).toBeDisabled();
  expect(writes).toBe(0);
  await page.screenshot({ path: `${evidence}/unknown-risk.png`, fullPage: true });
  await page.getByLabel('处理方式').selectOption('record_evidence');
  await page.getByLabel('核对记录或操作理由').fill('Provider outcome still unknown; preserving risk.');
  const recorded = page.waitForRequest(r => r.url().includes('/attempts/attempt_unknown/resolve'));
  await page.getByRole('button', { name: '提交处理决定' }).click();
  expect((await recorded).postDataJSON()).toEqual({decision: 'record_evidence', reason: 'Provider outcome still unknown; preserving risk.', duplicate_charge_risk_confirmed: false});
});

test('OCR warnings permit preflight submission after external consent', async ({ page }) => {
  const preflight = { import_id: 'preflight_contract', document_id: 'doc_contract', source_revision_id: 'source_contract', source_hash: 'a'.repeat(64), preflight_generation: 1, status: 'OCR_REQUIRED', page_count: 2, block_count: 1, unresolved_blocks: 1, source_language: 'en', blocks: [{ id: 'b1', kind: 'paragraph', normalized_text: 'Real extraction fixture', locators: [] }], pages: [{ page: 1, status: 'covered', covered_blocks: 1, unresolved_regions: 0 }, { page: 2, status: 'OCR_REQUIRED', covered_blocks: 0, unresolved_regions: 1 }] };
  await mock(page, { '/imports/preflight_contract/preflight': preflight, '/settings/provider': { ...provider, configured: true } });
  await page.goto('/#/preflight/preflight_contract');
  await page.getByLabel(/本任务费用上限/).fill('1');
  
  await page.getByLabel(/同意将必要的源文/).check();
  await expect(page.getByRole('button', { name: '确认外发与预算，开始翻译' })).toBeEnabled();
  await expect(page.getByText('此页暂无可靠文字').first()).toBeVisible();
});

test('protected atoms, unsaved text and stale QA preserve review boundaries', async ({ page }) => {
  const draft = { id: 'draft_contract', document_id: 'doc_contract', edition_id: 'edition_contract', source_revision_id: 'source_contract', source_hash: 'a'.repeat(64), generation: 2, target_locale: 'zh-Hans', glossary_revision: 'empty-v1', qa: { id: 'qa_stale', generation: 1, valid: true, fingerprint: 'old' }, source: { protected_atoms: { number: { value: '64' } } }, segments: [{ block_id: 'b1', source_text: 'It has 64 units.', target_inline: [{ type: 'text', text: '它有 ' }, { type: 'protected_ref', ref: 'number' }, { type: 'text', text: ' 个单元。' }], version: 1, source_hash: 'a'.repeat(64), context_hash: 'b'.repeat(64), review_status: 'machine_checked', locators: [{ page: 1, bbox: [10, 20, 90, 40], page_size: [100, 200] }, { page: 2, bbox: [20, 10, 80, 30], page_size: [100, 200] }] }], candidates: [] };
  await mock(page, { '/drafts/draft_contract': draft });
  await page.goto('/#/drafts/draft_contract');
  await expect(page.getByText('质量报告已过期', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '封存当前修订' })).toBeEnabled();
  await page.getByRole('button', { name: '展开段落 b1', exact: true }).click();
  await expect(page.getByText('保护内容：64')).toBeVisible();
  await page.getByRole('textbox', { name: '译文文本 1', exact: true }).fill('修正后的文本 ');
  await expect(page.getByText('有未保存修改')).toBeVisible();
  await expect(page.getByRole('button', { name: '运行质量检查' })).toBeDisabled();
  await page.getByRole('button', { name: '对照原 PDF', exact: true }).click();
  await expect(page.getByText('原 PDF · 第 1 页')).toBeVisible();
  await expect(page.getByText('原 PDF · 第 2 页')).toBeVisible();
  await page.screenshot({ path: `${evidence}/editor-desktop.png`, fullPage: true });
});

test('desktop, 390px and 320px layouts keep navigation and primary controls accessible', async ({ page }) => {
  await mock(page);
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1060 : 844 });
    await page.goto('/#/upload');
    await expect(page.getByRole('heading', { name: '上传 PDF', exact: true })).toBeVisible();
    const size = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: innerWidth }));
    expect(size.scroll).toBeLessThanOrEqual(size.width);
    if (width < 760) {
      await page.getByRole('button', { name: '打开菜单' }).click();
      await expect(page.getByRole('link', { name: '任务中心', exact: true })).toBeVisible();
      await page.getByRole('button', { name: '关闭菜单' }).click();
    }
    await page.screenshot({ path: `${evidence}/upload-${width}.png`, fullPage: true });
  }
});

test('unknown source language permits automatic detection and a changed selection clears consent', async ({ page }) => {
  const preflight = {import_id: 'und', document_id: doc.id, source_hash: 'a'.repeat(64), generation: 1, preflight_generation: 1, source_revision_id: 's1', source_language: 'und', status: 'ready', unresolved_blocks: 0, page_count: 1, block_count: 1, blocks: [{id: 'b1', kind: 'paragraph', normalized_text: 'Original sentence'}]};
  await mock(page, {'/imports/und/preflight': preflight, '/settings/provider': {...provider, configured: true}});
  await page.goto('/#/preflight/und');
  await page.getByLabel(/本任务费用上限/).fill('1');
  
  await page.getByLabel(/同意将必要的源文/).check();
  await expect(page.getByRole('button', {name: '确认外发与预算，开始翻译'})).toBeEnabled();
  await page.getByLabel('来源语言（可选指定）').selectOption('en');
  
  await expect(page.getByLabel(/同意将必要的源文/)).not.toBeChecked();
});

test('grouped candidates compare persisted bases and accept only explicit block with candidate ETag', async ({ page }) => {
  const candidate = {id: 'candidate_group', generation: 7, status: 'ready', base: {source_revision_id: 'source_contract', source_hash: 'a'.repeat(64), glossary_revision: 'empty-v1', requested_glossary_revision: 'new-glossary', segments: {b1: {version: 1, source_hash: 'b'.repeat(64), context_hash: 'c'.repeat(64), reviewed: true}}}, results: {b1: [{type: 'text', text: '候选已核对译文'}]}};
  const draft = {id: 'd', generation: 3, document_id: doc.id, edition_id: 'e', source_revision_id: 'source_contract', source_hash: 'a'.repeat(64), target_locale: 'zh-Hans', glossary_revision: 'empty-v1', source: {protected_atoms: {}}, segments: [{block_id: 'b1', version: 1, source_hash: 'b'.repeat(64), context_hash: 'c'.repeat(64), source_text: 'Original', target_inline: [{type: 'text', text: '现有人工译文'}], review_status: 'human_reviewed'}], candidates: [candidate]};
  await mock(page, {'/drafts/d': draft, '/candidates/candidate_group/accept': {status: 'accepted'}});
  await page.goto('/#/drafts/d');
  const accept = page.getByRole('button', {name: '接受 b1 候选'});
  await expect(accept).toBeDisabled();
  await page.getByLabel(/明确解除人工锁定/).check();
  await expect(accept).toBeEnabled();
  const sent = page.waitForRequest(r => r.url().includes('/candidates/candidate_group/accept'));
  await accept.click();
  const request = await sent;
  expect(request.headers()['if-match']).toBe('"7"');
  expect(request.postDataJSON()).toEqual({block_ids: ['b1'], allow_reviewed: true, glossary_revision: 'new-glossary'});
});

test('preflight native correction uses full persisted native text and explicit source evidence', async ({ page }) => {
  const bbox = [10, 10, 90, 30];
  const quote = 'Say “yes”.';
  const preflight = {import_id: 'native', document_id: doc.id, source_hash: 'a'.repeat(64), generation: 4, preflight_generation: 4, source_revision_id: 's', source_language: 'en', status: 'SOURCE_PARSE_REVIEW', unresolved_blocks: 1, unresolved: [{page: 1, bbox, text: quote}], page_count: 1, block_count: 1, blocks: [{id: 'b1', kind: 'paragraph', owner_id: null, normalized_text: "Say 'yes'."}]};
  const native = {generation: 4, pages: [{page: 1, page_size: [100, 200], text_regions: [{bbox, text: quote}]}], blocks: [{block_id: 'b1', native_text: quote, native_regions: [{page: 1, bbox, text: quote, page_size: [100, 200]}]}]};
  await mock(page, {'/imports/native/preflight': preflight, '/imports/native/native-regions': native, '/imports/native/corrections': {id: 'native2'}});
  await page.goto('/#/preflight/native');
  await page.getByRole('button', {name: '查看原文与调整解析', exact: true}).click();
  await expect(page.getByRole('button', {name: '创建新来源草稿并重检覆盖'})).toBeDisabled();
  await page.getByLabel('原件核对记录与理由').fill('Compared the original double quotation marks');
  await page.getByLabel(/我已对照高亮的原 PDF/).check();
  const sent = page.waitForRequest(r => r.url().includes('/imports/native/corrections'));
  await page.getByRole('button', {name: '创建新来源草稿并重检覆盖'}).click();
  const request = await sent;
  expect(request.postDataJSON().evidence).toEqual({page: 1, bbox, quote});
  expect(request.postDataJSON().operations).toEqual([{kind: 'replace_text', block_id: 'b1', start: 0, end: 10, text: quote}]);
  expect(request.headers()['if-match']).toBe('"1"'); // Mock's authoritative HTTP ETag.
});

test('unfinished draft export directly preserves labelled missing translations', async ({ page }) => {
  const draft = {id: 'draft_export', generation: 3, document_id: doc.id, edition_id: 'e', source_revision_id: 's', source_hash: 'a'.repeat(64), target_locale: 'zh-Hans', segments: [{block_id: 'b1', source_text: 'Missing target sentence.', target_inline: [], version: 0, source_hash: 'b'.repeat(64), review_status: 'not_reviewed'}]};
  await mock(page, {'/drafts/draft_export': draft, '/drafts/draft_export/exports': {export_id: 'export_draft'}, '/exports/export_draft': {status: 'succeeded', download_url: '/api/v1/exports/export_draft/download'}});
  await page.goto('/#/drafts/draft_export');
  await page.getByRole('button', {name: '导出已有内容', exact: true}).click();
  await expect(page.getByText('当前内容快照', {exact: true})).toBeVisible();
  await expect(page.getByText(/当前可见缺译 1 段/)).toBeVisible();
  const submit = page.getByRole('button', {name: '生成导出文件'});
  await expect(submit).toBeEnabled();
  await expect(page.getByLabel(/我明确导出未完成草稿/)).toHaveCount(0);
  const sent = page.waitForRequest(r => r.url().includes('/drafts/draft_export/exports'));
  await submit.click();
  expect((await sent).postDataJSON()).toEqual({format: 'single_html', include_source: false, confirm_draft: true});
  await expect(page.getByRole('link', {name: '下载文件'})).toHaveAttribute('href', '/api/v1/exports/export_draft/download');
});

test('owned caption math uses a reviewed annotation with Unicode offsets instead of splitting its owner',async({page})=>{
 const bbox=[25,22,32,28],pageHash='c'.repeat(64),text='😀 Figure: d model is 64.';
 const preflight={import_id:'caption_math',document_id:doc.id,source_hash:'a'.repeat(64),generation:1,status:'ready',source_language:'en',unresolved:[],unresolved_blocks:0,page_count:1,block_count:2,blocks:[{id:'figure',kind:'figure',provenance:[{page:1,bbox:[0,0,100,100],page_size:[100,200]}]},{id:'caption',kind:'caption',owner_id:'figure',normalized_text:text,provenance:[{page:1,bbox:[10,10,95,55],page_size:[100,200]}]}]};
 await mock(page,{'/imports/caption_math/preflight':preflight,'/imports/caption_math/native-regions':{generation:1,pages:[{page:1,page_size:[100,200],page_image_sha256:pageHash,text_regions:[{bbox,text:'d'}]}],blocks:[{block_id:'caption',native_text:text,native_regions:[{page:1,page_size:[100,200],bbox,text:'d'}]}]},'/imports/caption_math/corrections':{id:'next'}});
 await page.goto('/#/preflight/caption_math');await page.getByRole('button',{name:'查看原文与调整解析',exact:true}).click();await page.getByLabel('查看全部原生区域（含已覆盖）').check();await page.getByLabel('修正方式',{exact:true}).selectOption('math_annotation');await page.getByLabel('公式前的原文（精确前缀）').fill('😀 Figure: ');await page.getByLabel('公式后的原文（精确后缀）').fill(' is 64.');await page.getByLabel('公式裁图 x0').fill('24');await page.getByLabel('公式裁图 y0').fill('21');await page.getByLabel('公式裁图 x1').fill('44');await page.getByLabel('公式裁图 y1').fill('29');await page.getByLabel('原件核对记录与理由').fill('Original caption retains its owner; its exact d_model subscript is linked to original PDF pixels.');await expect(page.getByRole('button',{name:'创建新来源草稿并重检覆盖'})).toBeDisabled();await page.getByLabel(/我已逐字核对公式前后正文/).check();const sent=page.waitForRequest(r=>r.url().endsWith('/imports/caption_math/corrections'));await page.getByRole('button',{name:'创建新来源草稿并重检覆盖'}).click();expect((await sent).postDataJSON().operations).toEqual([{kind:'annotate_math_crop',block_id:'caption',start:10,end:17,page:1,bbox:[24,21,44,29],page_image_sha256:pageHash,visual_review_confirmed:true}]);
});

test('inline formula source correction binds a reviewed crop and exact surrounding text to the page hash', async ({ page }) => {
  const bbox = [35, 22, 39, 28];
  const source = 'The value is x / y in this formula.';
  const preflight = { import_id: 'math_native', document_id: doc.id, source_hash: 'a'.repeat(64), generation: 4, preflight_generation: 4, source_revision_id: 's', source_language: 'en', status: 'SOURCE_PARSE_REVIEW', unresolved_blocks: 1, unresolved: [{ page: 1, bbox, text: 'q' }], page_count: 1, block_count: 1, blocks: [{ id: 'b1', kind: 'paragraph', owner_id: null, normalized_text: source, provenance: [{ page: 1, bbox: [10, 10, 95, 55], page_size: [100, 200] }] }] };
  const native = { generation: 4, pages: [{ page: 1, page_size: [100, 200], page_image_sha256: 'f'.repeat(64), text_regions: [{ bbox, text: 'q' }] }], blocks: [{ block_id: 'b1', native_text: source, native_regions: [{ page: 1, bbox, text: 'q', page_size: [100, 200] }] }] };
  await mock(page, { '/imports/math_native/preflight': preflight, '/imports/math_native/native-regions': native, '/imports/math_native/corrections': { id: 'math_native_next' } });
  await page.goto('/#/preflight/math_native');
  await page.getByRole('button', { name: '查看原文与调整解析', exact: true }).click();
  await page.getByLabel('修正方式', { exact: true }).selectOption('math_crop');
  const submit = page.getByRole('button', { name: '创建新来源草稿并重检覆盖' });
  await expect(submit).toBeDisabled();
  await page.getByLabel('公式前的原文（精确前缀）').fill('The value is ');
  await page.getByLabel('公式后的原文（精确后缀）').fill(' in this formula.');
  await page.getByLabel('公式裁图 x0').fill('30');
  await page.getByLabel('公式裁图 y0').fill('20');
  await page.getByLabel('公式裁图 x1').fill('60');
  await page.getByLabel('公式裁图 y1').fill('35');
  await page.getByLabel('原件核对记录与理由').fill('Independently compared the source formula fraction and surrounding exact text.');
  await page.getByLabel(/我已逐字核对公式前后正文/).check();
  await expect(submit).toBeEnabled();
  await page.getByLabel('公式前的原文（精确前缀）').fill('A fabricated prefix');
  await expect(submit).toBeDisabled();
  await page.getByLabel('公式前的原文（精确前缀）').fill('The value is ');
  await page.getByLabel(/我已逐字核对公式前后正文/).check();
  const sent = page.waitForRequest(r => r.url().includes('/imports/math_native/corrections'));
  await submit.click();
  const request = await sent;
  expect(request.postDataJSON().evidence).toEqual({ page: 1, bbox, quote: 'q' });
  expect(request.postDataJSON().operations).toEqual([{ kind: 'split_with_math_crop', block_id: 'b1', page: 1, bbox: [30, 20, 60, 35], prefix: 'The value is ', suffix: ' in this formula.', page_image_sha256: 'f'.repeat(64), visual_review_confirmed: true }]);
  expect(request.headers()['if-match']).toBe('"1"');
});

test('semantic review reports the latest selected scope without claiming whole-draft or human certification',async({page})=>{
 const draft={id:'semantic',document_id:doc.id,edition_id:'edition',source_revision_id:'source',source_hash:'a'.repeat(64),generation:2,target_locale:'zh-Hans',segments:[{block_id:'p1',source_text:'One source.',target_inline:[{type:'text',text:'一段原文。'}],version:1,review_status:'not_reviewed'}],semantic_review_status:'not_requested',semantic_reviews:[] as {job_id:string;status:string;completed:boolean;block_ids:string[]}[]};
 await mock(page,{'/drafts/semantic':draft});await page.goto('/#/drafts/semantic');await expect(page.getByText('辅助语义评审：尚未请求。',{exact:true})).toBeVisible();
 for(const [state,status,completed,label] of [['incomplete','waiting_config',false,'未完成'],['incomplete','waiting_budget',false,'未完成'],['completed','succeeded',true,'最近所选范围已完成'],['stale','stale',false,'最近所选范围已过期']] as const){
  draft.semantic_review_status=state;draft.semantic_reviews=[{job_id:'semantic-job',status,completed,block_ids:['p1']}];await page.getByRole('button',{name:'读取最新版本',exact:true}).click();await expect(page.getByText(`辅助语义评审：${label}。`,{exact:true})).toBeVisible();const summary=page.getByRole('region',{name:'辅助语义评审范围'});await expect(summary).toContainText('最近请求：1 段 · p1');await expect(summary).toContainText('仅适用于该次明确所选段落，不代表全文完成、语义准确率或人工确认。');await expect(summary.getByRole('link',{name:'查看评审任务'})).toHaveAttribute('href','#/jobs/semantic-job');if(status==='waiting_config')await expect(summary).toContainText('等待翻译条件齐备');if(status==='waiting_budget')await expect(summary).toContainText('等待预算');
 }
 await page.screenshot({path:resolve(evidence,'semantic-stale-scope-contract.png'),fullPage:true});
});

test('permanent deletion opens the real cleanup job and displays only its safe file lifecycle summary',async({page})=>{
 const job={id:'cleanup-job',stage:'cleanup',status:'pending',generation:1,control_epoch:0,document_id:doc.id,cleanup:{online_content:'unavailable',files:'pending',shared_assets:'retained_while_referenced',backups:'retained_until_expiry',downloaded_copies:'outside_instance'}};
 await mock(page,{'/jobs/cleanup-job':job,'/jobs':{items:[job]}});await page.route('**/api/v1/documents/doc_contract',route=>route.fulfill({status:route.request().method()==='DELETE'?202:200,contentType:'application/json',headers:{ETag:'"1"'},body:JSON.stringify(route.request().method()==='DELETE'?{id:doc.id,status:'deleted',job_id:job.id}:doc)}));await page.goto('/#/documents/doc_contract');await page.getByRole('button',{name:'永久删除',exact:true}).click();await page.getByLabel('输入「删除」确认').fill('删除');const sent=page.waitForRequest(r=>r.method()==='DELETE');await page.getByRole('button',{name:'确认永久删除'}).click();expect((await sent).postDataJSON()).toEqual({confirm:true});await expect(page).toHaveURL(/#\/jobs\/cleanup-job/);
 const summary=page.getByRole('region',{name:'文档删除与文件清理'});await expect(summary).toContainText('等待文件清理');await expect(summary).toContainText('在线内容已不可访问');await expect(summary).toContainText('仍被其他文档引用的文件继续保留。');await expect(summary).toContainText('备份按保留期限淘汰；已下载的离线副本不能撤回。');
 for(const [state,status,label] of [['running','running','文件正在清理'],['completed','succeeded','可清理文件已完成清理'],['failed','failed','文件清理失败']] as const){job.cleanup.files=state;job.status=status;await page.reload();await expect(summary).toContainText(label);}
 await expect(page.getByRole('button',{name:'取消后续工作'})).toHaveCount(0);await expect(page.getByRole('button',{name:'暂停新派发'})).toHaveCount(0);await expect(page.getByRole('button',{name:'恢复安全缺失单元'})).toHaveCount(0);await expect(page.getByRole('link',{name:'文档详情',exact:true})).toHaveCount(0);await expect(page.locator('dt').filter({hasText:'实际费用'})).toHaveCount(0);await page.screenshot({path:resolve(evidence,'cleanup-status-contract.png'),fullPage:true});
});

test('mechanical native span uses Unicode offsets and stored page proof without accepting replacement text',async({page})=>{
 const bbox=[10,20,90,30],hash='a'.repeat(64),region={page:1,page_size:[100,200],bbox,text:'MLP block',native_indices:Array.from({length:9},(_,i)=>i)};
 const preflight={import_id:'native-span',document_id:doc.id,source_hash:'b'.repeat(64),generation:3,status:'ready',unresolved:[],unresolved_blocks:0,source_language:'en',page_count:1,block_count:1,blocks:[{id:'p',kind:'paragraph',normalized_text:'😀 MLPblock uses work.',provenance:[{page:1,bbox:[0,0,100,80],page_size:[100,200]}]}]};
 await mock(page,{'/imports/native-span/preflight':preflight,'/imports/native-span/native-regions':{generation:3,pages:[{page:1,page_size:[100,200],page_image_sha256:hash,text_regions:[region]}],blocks:[{block_id:'p',native_text:region.text,native_regions:[region]}]},'/imports/native-span/corrections':{id:'next'}});
 await page.route('**/api/v1/imports/native-span/preflight',r=>r.fulfill({contentType:'application/json',headers:{ETag:'"3"'},body:JSON.stringify(preflight)}));await page.goto('/#/preflight/native-span');await page.getByRole('button',{name:'查看原文与调整解析'}).click();await page.getByLabel('查看全部原生区域（含已覆盖）').check();await page.getByLabel('修正方式',{exact:true}).selectOption('native_span');await page.getByLabel('机械片段起点（Unicode 字符）').fill('2');await page.getByLabel('机械片段终点（不含此字符）').fill('10');await expect(page.getByText('MLPblock',{exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'创建新来源草稿并重检覆盖'})).toBeDisabled();await page.getByLabel('原件核对记录与理由').fill('Exact original native spacing is MLP block, selected current occurrence after the emoji.');await page.getByLabel(/我已核对选中片段与原生字形证据/).check();await page.getByLabel('机械片段终点（不含此字符）').fill('11');await expect(page.getByLabel(/我已核对选中片段与原生字形证据/)).not.toBeChecked();await expect(page.getByLabel('原件核对记录与理由')).toHaveValue('');await page.getByLabel('机械片段终点（不含此字符）').fill('10');await page.getByLabel('原件核对记录与理由').fill('Original MLP block has a visible separating space.');await page.getByLabel(/我已核对选中片段与原生字形证据/).check();await page.screenshot({path:resolve(evidence,'native-span-contract.png'),fullPage:true});const sent=page.waitForRequest(r=>r.url().endsWith('/imports/native-span/corrections'));await page.getByRole('button',{name:'创建新来源草稿并重检覆盖'}).click();const req=await sent;expect(req.headers()['if-match']).toBe('"3"');expect(req.postDataJSON()).toEqual({reason:'Original MLP block has a visible separating space.',evidence:{page:1,bbox,quote:'MLP block'},operations:[{kind:'normalize_native_span',block_id:'p',start:2,end:10,rule:'restore_native_spacing',page_image_sha256s:{'1':hash},visual_review_confirmed:true}]});
});

test('native continuation across a floating figure requires both exact regions and both page hashes',async({page})=>{
 const a={page:1,page_size:[100,200],bbox:[10,170,90,180],text:'We infer-',native_indices:Array.from({length:9},(_,i)=>i)},b={page:2,page_size:[100,200],bbox:[10,20,90,30],text:'ence is efficient.',native_indices:Array.from({length:18},(_,i)=>i)},ha='a'.repeat(64),hb='b'.repeat(64);
 const preflight={import_id:'native-merge',document_id:doc.id,source_hash:'c'.repeat(64),generation:1,status:'ready',unresolved:[],unresolved_blocks:0,source_language:'en',page_count:2,block_count:3,blocks:[{id:'first',kind:'paragraph',parent_id:null,owner_id:null,normalized_text:'We infer-',provenance:[{page:1,bbox:[10,150,90,180],page_size:[100,200]}]},{id:'figure',kind:'figure',owner_id:null,normalized_text:''},{id:'second',kind:'paragraph',parent_id:null,owner_id:null,normalized_text:'ence is efficient.',provenance:[{page:2,bbox:[10,20,90,70],page_size:[100,200]}]}]};
 await mock(page,{'/imports/native-merge/preflight':preflight,'/imports/native-merge/native-regions':{generation:1,pages:[{page:1,page_size:a.page_size,page_image_sha256:ha,text_regions:[a]},{page:2,page_size:b.page_size,page_image_sha256:hb,text_regions:[b]}],blocks:[{block_id:'first',native_text:a.text,native_regions:[a]},{block_id:'second',native_text:b.text,native_regions:[b]}]},'/imports/native-merge/corrections':{id:'next'}});await page.goto('/#/preflight/native-merge');await page.getByRole('button',{name:'查看原文与调整解析'}).click();await page.getByLabel('查看全部原生区域（含已覆盖）').check();await page.getByLabel('修正方式',{exact:true}).selectOption('native_merge');await expect(page.getByText('保留中间图表与公式：figure',{exact:true})).toBeVisible();await expect(page.getByLabel('续接来源块')).toHaveValue('second');await expect(page.getByRole('button',{name:'创建新来源草稿并重检覆盖'})).toBeDisabled();await page.getByLabel('续接原生行证据').selectOption('0');await page.getByLabel('原件核对记录与理由').fill('Original page1 final infer- continues as ence on page2; preserve intervening figure.');await page.getByLabel(/我已核对选中片段与原生字形证据/).check();await page.screenshot({path:resolve(evidence,'native-float-contract.png'),fullPage:true});const sent=page.waitForRequest(r=>r.url().endsWith('/imports/native-merge/corrections'));await page.getByRole('button',{name:'创建新来源草稿并重检覆盖'}).click();expect((await sent).postDataJSON().operations).toEqual([{kind:'merge_native_continuation',block_ids:['first','second'],rule:'remove_line_wrap',continuation_evidence:{page:2,bbox:b.bbox,quote:b.text},page_image_sha256s:{'1':ha,'2':hb},visual_review_confirmed:true}]);
});
