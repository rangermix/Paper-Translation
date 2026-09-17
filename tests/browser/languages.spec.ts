import {test,expect,type Page} from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory, outputPath } from './paths';
import {resolve} from 'node:path';
const profile={endpoint:'http://local-ai:11434/v1/chat/completions',api_protocol:'chat_completions',auth_mode:'none',configured:true,provider:'openai',model_id:'fixed-test-model',profile_revision:'profile1',profile_hash:'f'.repeat(64),currency:'USD',semantic_review_enabled:true,enabled_pairs:[['en','zh-Hans']],locale_matrix:[{source:'en',target:'zh-Hans',enabled:true}],experimental_locales:['en','zh-Hans','zh-Hant','ja','de','ar','unknown']};
const doc={id:'d',generation:1,title:'多语言文档',source_language:'en',source_revision_id:'s',source_asset_id:'pdf',starred:false,tags:[],lifecycle:'active',editions:[]};
const preflight={generation:1,preflight_generation:1,import_id:'i',document_id:'d',source_revision_id:'s',source_hash:'a'.repeat(64),source_language:'en',status:'ready',unresolved_blocks:0,page_count:1,block_count:1,blocks:[{id:'b1',kind:'paragraph',normalized_text:'The value is 64.'}]};
const draft={id:'draft',generation:1,document_id:'d',edition_id:'e',experimental:true,source_revision_id:'s',source_hash:'a'.repeat(64),target_locale:'de',glossary_revision:'empty-v1',source:{language:'en',protected_atoms:{}},segments:[{block_id:'b1',source_text:'Original sentence.',source_hash:'b'.repeat(64),context_hash:'c'.repeat(64),version:1,review_status:'not_reviewed',target_inline:[{type:'text',text:'Manueller Test.'}]}]};
async function mock(page:Page){
 const routes:Record<string,unknown>={'/capabilities':{phase:'M2',source_mime_types:['application/pdf']},'/settings/provider':profile,'/settings/preferences':{generation:1,locale:'zh-Hans',publish_policy:'manual_approval'},'/documents/d':doc,'/imports/i/preflight':preflight,'/drafts/draft':draft,'/glossaries/effective':{revision:'empty-v1'},'/jobs':{items:[]},'/settings/dispatch':{generation:1,dispatch_disabled:true,unknown_count:0,inflight_count:0},'/jobs/j':{id:'j',generation:1,stage:'translating',status:'queued',control_epoch:0,experimental:true},'/editions/e/preflight':{profile_hash:profile.profile_hash,generation:1,source_revision_id:'s',source_hash:'a'.repeat(64),source_language:'en',locale:'zh-Hant',can_translate:true,profile},'/imports/i/confirm':{job_id:'j'},'/documents/d/editions':{id:'e'},'/editions/e/translate':{job_id:'j'},'/drafts/draft/candidates':{job_id:'j'},'/drafts/draft/semantic-review':{job_id:'j'}};
 await page.route('**/api/v1/**',route=>{const path=new URL(route.request().url()).pathname.slice(7);if(path.endsWith('/events'))return route.abort();return route.fulfill({status:routes[path]===undefined?404:200,contentType:'application/json',headers:{ETag:'"1"'},body:JSON.stringify(routes[path]??{error:{code:'MISSING'}})});});
}
async function expectDestination(page:Page){
 const destination=page.getByRole('region',{name:'本次请求目的地'});
 await expect(destination).toContainText(profile.endpoint);
 await expect(destination).toContainText('Chat Completions');
 await expect(destination).toContainText('无鉴权，不发送 Authorization');
 await expect(destination).toContainText(profile.model_id);
}

test('all languages show native names and allow normal auto-publication after ordinary consent',async({page})=>{
 await mock(page);await page.goto('/#/preflight/i');await expectDestination(page);
 await expect(page.getByLabel('显示实验语言',{exact:true})).toHaveCount(0);
 const target=page.getByLabel('目标语言',{exact:true});
 for (const [code,name] of [['en','English'],['ja','日本語'],['de','Deutsch'],['zh-Hant','繁體中文'],['fr','français'],['ar','العربية']]) {
   await expect(target.locator(`option[value="${code}"]`)).toHaveText(name);
 }
 await page.getByLabel('来源语言（可选指定）',{exact:true}).selectOption('ko');
 await target.selectOption('ar');
 await page.getByLabel('发布方式').selectOption('auto_publish');
 await page.getByLabel(/本任务费用上限/).fill('0.01');
 const submit=page.getByRole('button',{name:'确认外发与预算，开始翻译'});
 await expect(submit).toBeDisabled();await page.getByLabel(/同意将必要的源文/).check();await expect(submit).toBeEnabled();
 await target.selectOption('fr');await expect(page.getByLabel(/同意将必要的源文/)).not.toBeChecked();
 await page.getByLabel(/同意将必要的源文/).check();
 await page.screenshot({path:resolve(outputDirectory('screenshots'),'languages-preflight-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
 await page.screenshot({path:resolve(outputDirectory('screenshots'),'languages-preflight-mobile.png'),fullPage:true});
 const sent=page.waitForRequest(r=>r.url().endsWith('/imports/i/confirm'));await submit.click();
 const body=(await sent).postDataJSON();expect(body).toMatchObject({source_language:'ko',locale:'fr',publish_policy:'auto_publish',profile_hash:profile.profile_hash});
 expect(body).not.toHaveProperty('experimental_confirmed');await expect(page.getByText('实验语言 · 未认证',{exact:true})).toHaveCount(0);
});

test('missing profile hash still blocks translation',async({page})=>{
 await mock(page);await page.route('**/api/v1/settings/provider',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({...profile,profile_hash:undefined})}));
 await page.goto('/#/preflight/i');await page.getByLabel(/本任务费用上限/).fill('0.01');await page.getByLabel(/同意将必要的源文/).check();
 await expect(page.getByRole('button',{name:'确认外发与预算，开始翻译'})).toBeDisabled();
});

test('new language edition uses native names and independent ordinary translation consent',async({page})=>{
 await mock(page);await page.goto('/#/documents/d');await page.getByLabel('新增语言版',{exact:true}).selectOption('zh-Hant');
 const created=page.waitForRequest(r=>r.url().endsWith('/documents/d/editions')&&r.method()==='POST');await page.getByRole('button',{name:'新增',exact:true}).click();
 expect((await created).postDataJSON()).toEqual({target_locale:'zh-Hant',source_revision_id:'s',profile_hash:profile.profile_hash});
 const dialog=page.getByRole('dialog');await expectDestination(page);await expect(dialog).toContainText('English → 繁體中文');
 await dialog.getByLabel(/此语言版任务预算/).fill('0.01');
 const submit=dialog.getByRole('button',{name:'确认外发与预算，翻译此语言版'});await expect(submit).toBeDisabled();
 await dialog.getByLabel(/同意向上述服务地址/).check();await dialog.getByLabel('发布方式').selectOption('auto_publish');
 const sent=page.waitForRequest(r=>r.url().endsWith('/editions/e/translate'));await submit.click();
 const body=(await sent).postDataJSON();expect(body).toMatchObject({profile_hash:profile.profile_hash,publish_policy:'auto_publish'});expect(body).not.toHaveProperty('experimental_confirmed');
});

for(const mode of ['candidate','semantic'])test(`${mode} accepts any language with normal external consent, including legacy drafts`,async({page})=>{
 await mock(page);await page.goto('/#/drafts/draft');await expect(page.getByText('实验语言 · 未认证',{exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'展开段落 b1',exact:true}).click();await expect(page.getByText('译文 · Deutsch',{exact:true})).toBeVisible();
 await page.getByLabel('选择段落 b1',{exact:true}).check();await page.getByRole('button',{name:mode==='candidate'?/局部重译/:/辅助语义评审/}).click();
 const dialog=page.getByRole('dialog');await expectDestination(page);await dialog.getByLabel(/候选任务预算/).fill('0.01');
 const submit=dialog.getByRole('button',{name:mode==='candidate'?'创建局部候选任务':'创建辅助语义评审任务'});await expect(submit).toBeDisabled();
 await dialog.getByLabel(/我同意向上述服务地址/).check();const suffix=mode==='candidate'?'candidates':'semantic-review';
 const sent=page.waitForRequest(r=>r.url().endsWith('/'+suffix));await submit.click();const body=(await sent).postDataJSON();
 expect(body).toMatchObject({profile_hash:profile.profile_hash,block_ids:['b1']});expect(body).not.toHaveProperty('experimental_confirmed');
});

test('settings and upload expose all native names and accept additional language tags',async({page})=>{
 await mock(page);await page.goto('/#/settings');
 const select=page.getByLabel('默认目标语言',{exact:true});await select.selectOption('ja');
 await expect(select.locator('option:checked')).toHaveText('日本語');
 await select.selectOption('__custom');await page.getByLabel('语言代码（如 fil、pt-BR）',{exact:true}).fill('ast');
 const saved=page.waitForRequest(r=>r.url().endsWith('/settings/preferences')&&r.method()==='PATCH');await page.getByRole('button',{name:'保存偏好',exact:true}).click();expect((await saved).postDataJSON().locale).toBe('ast');
 await page.goto('/#/upload');await page.getByLabel('默认目标语言',{exact:true}).selectOption('pt-BR');
 await expect(page.getByLabel('默认目标语言',{exact:true}).locator('option:checked')).toHaveText('português (Brasil)');
});

test('history filtering uses locale codes while displaying native names',async({page})=>{
 await mock(page);
 const editions=[{id:'e-ja',target_locale:'ja',current_artifact_id:'a-ja'},{id:'e-de',target_locale:'de',current_artifact_id:'a-de'}];
 await page.route('**/api/v1/documents/d',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({...doc,editions})}));
 await page.route('**/api/v1/documents/d/history',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({artifacts:editions.map(e=>({id:e.current_artifact_id,edition_id:e.id,locale:e.target_locale,template_id:'reader-v1'})),sources:[],translations:[]})}));
 await page.route('**/api/v1/templates',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({items:[]})}));
 await page.goto('/#/history/d');await page.getByRole('combobox',{name:'语言',exact:true}).selectOption('ja');
 await expect(page.getByRole('heading',{name:'日本語 · reader-v1',exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Deutsch · reader-v1',exact:true})).toHaveCount(0);
 await expect(page.getByRole('link',{name:'阅读这个版本'})).toHaveAttribute('href','/artifacts/a-ja/index.html');
});
