import { test, expect, type Page } from '../../apps/web/node_modules/@playwright/test/index.mjs';
import { outputPath } from './paths';
import { resolve } from 'node:path';

const evidence = process.env.COST_UI_EVIDENCE ? outputPath(process.env.COST_UI_EVIDENCE) : undefined;
const profile = { generation: 3, configured: true, dispatch_configuration_ready: true, config_source: 'managed', has_api_key: true,
  provider: 'openai', api_protocol: 'responses', auth_mode: 'bearer', endpoint: 'https://custom.example/my-service', model_id: 'custom-model:latest',
  profile_hash: 'a'.repeat(64), profile_revision: 'fixture-profile-3', enabled_pairs: [['en', 'zh-Hans']],
  semantic_review_enabled: true, max_input_tokens: 8000, max_output_tokens: 2000,
  price: { currency: 'USD', input_micro_per_million: 1000000, cached_input_micro_per_million: 200000, output_micro_per_million: 2000000,
    output_includes_reasoning: true, input_bound_rule: 'utf8-byte-ceiling-v1', revision: 'fixture-price' } };
async function setup(page: Page, value: Record<string, unknown> = profile) {
  const writes: { path: string; body: Record<string, any>; headers: Record<string, string> }[] = [];
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const doc = { id: 'doc', generation: 1, title: 'Native service contract', lifecycle: 'active', starred: false, tags: [], source_asset_id: 'pdf', source_revision_id: 'source', source_language: 'en', editions: [{ id: 'edition', target_locale: 'zh-Hans' }] };
  const source = { generation: 1, preflight_generation: 1, import_id: 'import', document_id: 'doc', source_revision_id: 'source', source_hash: 'b'.repeat(64), profile_hash: value.profile_hash, source_language: 'en', status: 'ready', unresolved_blocks: 0, page_count: 1, block_count: 1, blocks: [{ id: 'b1', kind: 'paragraph', normalized_text: 'The value is 64.' }] };
  const draft = { id: 'draft', generation: 1, document_id: 'doc', edition_id: 'edition', source_revision_id: 'source', source_hash: source.source_hash, target_locale: 'zh-Hans', glossary_revision: 'empty-v1', source: { language: 'en', protected_atoms: {} }, segments: [{ block_id: 'b1', source_text: 'Original sentence.', source_hash: 'c'.repeat(64), context_hash: 'd'.repeat(64), version: 1, review_status: 'unreviewed', target_inline: [{ type: 'text', text: '已有译文' }] }] };
  await page.route('**/api/v1/**', async route => {
    const request = route.request(); const path = new URL(request.url()).pathname.slice(7);
    if (request.method() !== 'GET') {
      writes.push({ path, body: request.postDataJSON(), headers: request.headers() });
      return route.fulfill({ json: path === '/settings/provider' ? { ...value, ...request.postDataJSON().profile, generation: 4, has_api_key: !request.postDataJSON().clear_api_key, dispatch_configuration_ready: !request.postDataJSON().clear_api_key } : { job_id: 'job' }, headers: { ETag: '"4"' } });
    }
    const routes: Record<string, unknown> = { '/settings/provider': value,
      '/settings/dispatch': { generation: 1, dispatch_disabled: true, maintenance: false, unknown_attempts: 0, unknown_micro: 0, inflight_requests: 0 },
      '/settings/preferences': { generation: 1, locale: 'zh-Hans', publish_policy: 'manual_approval' },
      '/capabilities': { phase: 'M2', source_mime_types: ['application/pdf'] }, '/documents/doc': doc, '/drafts/draft': draft,
      '/imports/import/preflight': source, '/glossaries/effective': { revision: 'empty-v1' },
      '/editions/edition/preflight': { ...source, generation: 1, locale: 'zh-Hans', can_translate: true, profile: value },
      '/jobs/job': { id: 'job', generation: 1, status: 'queued', stage: 'translating', control_epoch: 0 }, '/jobs': { items: [] } };
    if (path.endsWith('/events')) return route.abort();
    return route.fulfill({ json: routes[path] ?? { items: [] }, headers: { ETag: path === '/settings/provider' ? '"3"' : '"1"' } });
  });
  return { writes, errors };
}
const save = (page: Page) => page.getByRole('button', { name: '保存 AI 服务配置', exact: true });


const defaults = { max_input_tokens: 32768, max_output_tokens: 8192, max_unit_characters: 2000 };
const costToggle = (page: Page) => page.getByLabel('启用预算与成本控制', { exact: true });
const limits = (page: Page) => [page.getByLabel('单次输入 token 上限', { exact: true }), page.getByLabel('单次输出 token 上限', { exact: true }), page.getByLabel('单个翻译单元字符上限', { exact: true })];
async function advanced(page: Page) { await page.getByText('高级选项：价格与请求限制', { exact: true }).click(); }

test('new unconfigured service shows disabled optional costs and actual server token defaults', async ({ page }) => {
  const { writes, errors } = await setup(page, { generation: 0, configured: false, config_source: 'unconfigured', has_api_key: false, cost_control_enabled: false, token_limits_defaults: defaults, ...defaults });
  await page.goto('/#/settings');
  await expect(costToggle(page)).not.toBeChecked();
  await advanced(page);
  for (const [i, value] of Object.values(defaults).entries()) await expect(limits(page)[i]).toHaveValue(String(value));
  await expect(page.getByLabel('输入价格（USD / 百万 token）', { exact: true })).toHaveValue('');
  await save(page).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.profile).toMatchObject({ cost_control_enabled: false, ...defaults });
  expect(writes[0].body.profile).not.toHaveProperty('price');
  expect(writes[0].body.profile).not.toHaveProperty('token_limits_defaults');
  expect(writes[0].body).not.toHaveProperty('api_key');
  expect(errors).toEqual([]);
});

test('legacy absent cost flag remains on and switching off preserves prices and stored key', async ({ page }) => {
  const { writes } = await setup(page);
  await page.goto('/#/settings');
  await expect(costToggle(page)).toBeChecked();
  await costToggle(page).uncheck();
  expect(writes).toHaveLength(0);
  await save(page).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.profile).toMatchObject({ cost_control_enabled: false, endpoint: profile.endpoint, model_id: profile.model_id, price: { input_micro_per_million: 1000000, cached_input_micro_per_million: 200000, output_micro_per_million: 2000000 } });
  expect(writes[0].body).not.toHaveProperty('api_key');
  expect(writes[0].body).not.toHaveProperty('clear_api_key');
});

test('reset and undo limits use server defaults only and preserve every other pending input', async ({ page }) => {
  const { writes } = await setup(page, { ...profile, max_unit_characters: 500, token_limits_defaults: defaults });
  await page.goto('/#/settings'); await advanced(page);
  await page.getByLabel('模型 ID', { exact: true }).fill('pending-model');
  await page.getByLabel('API 密钥', { exact: true }).fill('synthetic-pending-key');
  await costToggle(page).uncheck();
  await page.getByLabel('输入价格（USD / 百万 token）', { exact: true }).fill('3');
  await limits(page)[0].fill('9000');
  await page.getByRole('button', { name: '重置请求限制', exact: true }).click();
  for (const [i, value] of Object.values(defaults).entries()) await expect(limits(page)[i]).toHaveValue(String(value));
  await page.getByRole('button', { name: '撤销限额修改', exact: true }).click();
  for (const [i, value] of [8000, 2000, 500].entries()) await expect(limits(page)[i]).toHaveValue(String(value));
  await expect(page.getByLabel('完整请求 URL', { exact: true })).toHaveValue(profile.endpoint);
  await expect(page.getByLabel('模型 ID', { exact: true })).toHaveValue('pending-model');
  await expect(page.getByLabel('API 密钥', { exact: true })).toHaveValue('synthetic-pending-key');
  await expect(costToggle(page)).not.toBeChecked();
  await expect(page.getByLabel('输入价格（USD / 百万 token）', { exact: true })).toHaveValue('3');
  expect(writes).toHaveLength(0);
});

test('effective Claude API version is a value instead of only a placeholder', async ({ page }) => {
  await setup(page, { ...profile, provider: 'anthropic', api_protocol: 'claude_messages', auth_mode: 'api_key', api_version: undefined });
  await page.goto('/#/settings'); await advanced(page);
  await expect(page.getByLabel('Anthropic API 版本', { exact: true })).toHaveValue('2023-06-01');
});

for (const enabled of [false, true]) for (const flow of ['preflight', 'edition', 'candidate', 'semantic'] as const) test(`${flow} ${enabled ? 'controlled' : 'uncontrolled'} requires external consent and submits the matching budget shape`, async ({ page }) => {
  const { writes } = await setup(page, { ...profile, cost_control_enabled: enabled, ...(enabled ? {} : { price: null }) });
  await page.goto(flow === 'preflight' ? '/#/preflight/import' : flow === 'edition' ? '/#/documents/doc' : '/#/drafts/draft');
  if (flow === 'edition') await page.getByRole('button', { name: '确认此语言版翻译', exact: true }).click();
  if (flow === 'candidate' || flow === 'semantic') { await page.getByLabel('选择段落 b1', { exact: true }).check(); await page.getByRole('button', { name: flow === 'candidate' ? /局部重译/ : /辅助语义评审/ }).click(); }
  const submit = page.getByRole('button', { name: flow === 'preflight' ? /开始翻译$/ : flow === 'edition' ? /翻译此语言版$/ : flow === 'candidate' ? '创建局部候选任务' : '创建辅助语义评审任务', exact: flow === 'candidate' || flow === 'semantic' });
  const budget = page.locator('#translation-budget, #candidate-budget, input[type=number]');
  await expect(submit).toBeDisabled();
  if (enabled) { await expect(budget).toHaveCount(1); await budget.fill('0.01'); }
  else { await expect(budget).toHaveCount(0); await expect(page.getByText(/未启用预算与成本控制/).last()).toBeVisible(); }
  
  
  await expect(submit).toBeDisabled();
  await page.getByLabel(flow === 'candidate' || flow === 'semantic' ? /我同意向上述服务地址/ : /同意将必要的源文|同意向上述服务地址/).check();
  await expect(submit).toBeEnabled(); await submit.click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body).toMatchObject({ external_processing_confirmed: true, profile_hash: profile.profile_hash });
  if (enabled) expect(writes[0].body.budget_micro).toBe(10000); else expect(writes[0].body).not.toHaveProperty('budget_micro');
});

test('latest configuration comparison shows cost mode and effective limits before adopting its generation', async ({ page }) => {
  const { writes } = await setup(page, { ...profile, cost_control_enabled: true });
  await page.goto('/#/settings');
  await costToggle(page).uncheck();
  await page.route('**/api/v1/settings/provider', async route => route.request().method() === 'GET'
    ? route.fulfill({ json: { ...profile, generation: 9, cost_control_enabled: true, ...defaults, token_limits_defaults: defaults }, headers: { ETag: '"9"' } })
    : route.fallback());
  await page.getByRole('button', { name: '读取最新配置', exact: true }).click();
  const comparison=page.getByRole('region', { name: '配置版本比较' });
  await expect(comparison).toContainText('预算与成本控制'); await expect(comparison).toContainText('已启用');
  await expect(comparison).toContainText('32768 / 8192');
  await page.getByRole('button', { name: '保留输入并采用最新版本', exact: true }).click();
  await expect(costToggle(page)).not.toBeChecked();
  await save(page).click(); await expect.poll(()=>writes.length).toBe(1);
  expect(writes[0].headers['if-match']).toBe('"9"');
  expect(writes[0].body.profile.cost_control_enabled).toBe(false);
});

for (const enabled of [false, true]) test(`unknown retry uses frozen job cost mode ${enabled} even when current settings differ`, async ({ page }) => {
  const { writes } = await setup(page, { ...profile, cost_control_enabled: !enabled });
  const job={ id:'job', generation:4, control_epoch:2, status:'outcome_unknown', stage:'translating', cost_control_enabled:enabled, actual_micro:null, reserved_micro:null, unknown_micro:enabled?20480:null, budget_micro:enabled?1000000:null, attempts:[{id:'unknown',status:'outcome_unknown'}] };
  await page.route('**/api/v1/jobs/job', route=>route.fulfill({json:job,headers:{ETag:'"4"'}}));
  await page.goto('/#/jobs/job');
  await expect(page.getByText('未计算',{exact:true}).first()).toBeVisible();
  if(enabled) await expect(page.getByText('USD 0.020480',{exact:true})).toBeVisible();
  else { await expect(page.getByText('未限制',{exact:true})).toBeVisible(); await expect(page.locator('body')).not.toContainText('USD 0.000000'); }
  await page.getByRole('button',{name:'核对未知请求',exact:true}).click();
  await page.getByLabel('处理方式',{exact:true}).selectOption('retry_accept_risk');
  await page.getByLabel('核对记录或操作理由',{exact:true}).fill('Synthetic contract: verified request outcome is still unknown.');
  const submit=page.getByRole('button',{name:'提交处理决定',exact:true});
  await expect(submit).toBeDisabled();
  const budget=page.getByLabel(/重新确认任务预算/);
  if(enabled) { await expect(budget).toBeVisible(); await budget.fill('1'); }
  else await expect(budget).toHaveCount(0);
  await expect(submit).toBeDisabled();
  await page.getByLabel(/我同意向本任务原先确认的服务重新发起请求/).check();
  await expect(submit).toBeEnabled(); await submit.click();
  await expect.poll(()=>writes.length).toBe(1);
  expect(writes[0].body).toMatchObject({decision:'retry_accept_risk',duplicate_charge_risk_confirmed:true});
  if(enabled) expect(writes[0].body.budget_micro).toBe(1000000); else expect(writes[0].body).not.toHaveProperty('budget_micro');
});

test('optional costs and actual limits render at desktop and mobile without blank page or horizontal overflow',async({page},testInfo)=>{
  const {errors}=await setup(page,{...profile,cost_control_enabled:false,token_limits_defaults:defaults,...defaults,price:null,provider:'anthropic',api_protocol:'claude_messages',auth_mode:'api_key'});
  for(const [label,width,height] of [['desktop',1440,1060],['mobile',390,844]] as const){
    await page.setViewportSize({width,height}); await page.goto('/#/settings'); await page.reload(); await advanced(page);
    await expect(limits(page)[0]).toBeVisible(); await expect(limits(page)[0]).toHaveValue('32768');
    await expect(page).toHaveTitle(/对照文库/); await expect(page.getByRole('heading',{name:'AI 服务',exact:true})).toBeVisible();
    await expect(page.locator('vite-error-overlay')).toHaveCount(0);
    await expect(costToggle(page)).not.toBeChecked();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.evaluate(()=>scrollTo(0,0));
    await page.screenshot({path:evidence ? resolve(evidence,`settings-cost-${label}.png`) : testInfo.outputPath(`settings-cost-${label}.png`),fullPage:true});
  }
  expect(errors).toEqual([]);
});
