import { test, expect } from '../../apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';
import { resolve } from 'node:path';
import { writeFile } from 'node:fs/promises';
const root = resolve(import.meta.dirname, '../..');
test('real inspector rejects one selected PDF while the following PDF is saved independently', async ({page}) => {
  test.skip(process.env.LIBRARY_LIVE_E2E !== '1', 'Requires designated local acceptance instance; no provider calls.');
  test.setTimeout(90000);
  const posts: {path:string;status:number}[]=[];
  page.on('response', r => {if(r.request().method()!=='GET') posts.push({path:new URL(r.url()).pathname,status:r.status()});});
  await page.goto('/#/upload');
  await page.locator('input[type=file]').setInputFiles([resolve(root,'fixtures/security/malformed.pdf'),resolve(root,'fixtures/sample.pdf')]);
  await page.getByRole('button',{name:'保存 PDF 原件',exact:true}).click();
  const failed=page.locator('.file-result').filter({has:page.getByText('malformed.pdf',{exact:true})});
  const valid=page.locator('.file-result').filter({has:page.getByText('sample.pdf',{exact:true})});
  await expect(failed.getByRole('alert')).toContainText('PDF 检查失败',{timeout:60000});
  const saved=valid.getByRole('link',{name:'原件已保存 · 管理文档'});
  const duplicate=valid.getByRole('button',{name:'建立独立文档'});
  await expect(saved.or(duplicate)).toBeVisible({timeout:60000});
  if(await duplicate.isVisible()) await duplicate.click();
  await expect(saved).toBeVisible();
  await expect(failed.getByRole('link')).toHaveCount(0);
  expect(posts.filter(p=>p.path==='/api/v1/imports')).toHaveLength(1);
  expect(posts.filter(p=>/confirm|translate/.test(p.path))).toHaveLength(0);
  const href=await saved.getAttribute('href');
  await page.screenshot({path:resolve(outputDirectory('live'), 'live-multiple-independent.png'),fullPage:true});
  await saved.click();
  await page.getByRole('button',{name:'编辑题名与标签'}).click();
  const title=`Agent multi-file isolation ${Date.now()}`;
  await page.getByLabel('题名',{exact:true}).fill(title);
  await page.getByLabel('标签（逗号分隔）').fill('agent-acceptance, upload-isolation');
  await page.getByRole('button',{name:'保存目录信息',exact:true}).click();
  await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();
  await page.getByRole('button',{name:'归档文档',exact:true}).click();
  await expect(page.getByRole('button',{name:'取消归档',exact:true})).toBeVisible();
  await writeFile(resolve(outputDirectory('live'), 'live-multiple-independent.json'),JSON.stringify({kind:'actual_browser_actual_HTTP_native_inspector',href,title,posts,failed_document_created:false,provider_calls:0},null,2));
});

test('real EventSource reconnect carries its server cursor and reloads authoritative generation after offline recovery',async({page,context})=>{
  test.skip(process.env.LIBRARY_LIVE_E2E !== '1','Read-only real job snapshot/events check.');
  test.setTimeout(60000);
  const jobs=await page.request.get('/api/v1/jobs?limit=100').then(r=>r.json());
  let chosen:any;let cursor='';
  for(const j of jobs.items){const body=await page.request.get(`/api/v1/jobs/${j.id}/events`).then(r=>r.text()); const ids=[...body.matchAll(/^id: (.+)$/gm)];if(ids.length){chosen=j;cursor=ids.at(-1)![1];break;}}
  expect(chosen,'An existing durable job event is required').toBeTruthy();
  const cursors:string[]=[];const generations:number[]=[];let expiredCursorSent=false;let snapshotRequired=false;
  page.on('request',async r=>{if(r.url().includes(`/jobs/${chosen.id}/events`))cursors.push((await r.allHeaders())['last-event-id']??'');});
  page.on('response',async r=>{if(new URL(r.url()).pathname===`/api/v1/jobs/${chosen.id}` && r.status()===200){try{generations.push((await r.json()).generation);}catch{}}});
  await page.goto(`/#/jobs/${chosen.id}`);
  await expect(page.locator('.task-layout > .panel h2').first()).toBeVisible();
  await page.getByText('任务技术信息',{exact:true}).click();
  await expect(page.locator('.job-technical')).toContainText(chosen.id);
  await expect.poll(()=>cursors.includes(cursor),{timeout:15000}).toBe(true);
  await context.setOffline(true);
  await expect(page.getByText(/定时更新/)).toBeVisible();
  const before=generations.length;
  // Exercise a missing/expired cursor against the real server without changing its event store.
  await page.route(`**/api/v1/jobs/${chosen.id}/events`,async route=>{
    if(expiredCursorSent){await route.continue();return;}
    expiredCursorSent=true;
    const response=await route.fetch({headers:{...await route.request().allHeaders(),'Last-Event-ID':'event_expired_independent_browser_fixture'}});
    const text=await response.text();snapshotRequired=text.includes('event: snapshot_required');
    await route.fulfill({response,body:text});
  });
  await context.setOffline(false);
  await expect.poll(()=>snapshotRequired,{timeout:15000}).toBe(true);
  await expect.poll(()=>generations.length,{timeout:15000}).toBeGreaterThan(before);
  const current=await page.request.get(`/api/v1/jobs/${chosen.id}`).then(r=>r.json());
  expect(generations.at(-1)).toBe(current.generation);
  expect(cursors.filter(c=>c===cursor).length).toBeGreaterThanOrEqual(1);
  await expect(page.locator('.job-technical dd').last()).toHaveText(`${current.generation} / ${current.control_epoch}`);
  await page.screenshot({path:resolve(outputDirectory('live'), 'live-sse-reconnect.png'),fullPage:true});
  await writeFile(resolve(outputDirectory('live'), 'live-sse-reconnect.json'),JSON.stringify({kind:'actual_native_EventSource_actual_HTTP',job_id:chosen.id,server_cursor:cursor,cursors,generations,authoritative_generation:current.generation,offline_recovery:true,expired_cursor_injected_at_transport:expiredCursorSent,real_server_snapshot_required:snapshotRequired,mutations:0},null,2));
});
